"""Smoke test for src.setup.first_run (first-run setup GUI).

Plain asyncio script (no pytest), styled after tests/browser_smoke.py. Drives
run_first_run_setup as a background asyncio task per scenario against a temp
env_path (never touches the repo's real .env) with an injected fake
validator, so no real network call ever hits Deepgram/OpenAI/Cartesia.

Run: cd demo-agent && .venv/bin/python tests/setup_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.setup.first_run import run_first_run_setup  # noqa: E402

CLOUD_KEY_FIELDS = ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY")


async def _wait_ready(base_url: str, client: httpx.AsyncClient, attempts: int = 60) -> None:
    """Poll GET / until the server is accepting connections."""
    for _ in range(attempts):
        try:
            resp = await client.get(base_url + "/")
            if resp.status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.05)
    raise AssertionError(f"server at {base_url} never became ready")


async def scenario_fresh_env_full_save() -> None:
    """Steps 1-3: fresh env_path (absent), always-ok validator, full save."""
    with tempfile.TemporaryDirectory() as tmp:
        env_path = str(Path(tmp) / ".env")
        base = "http://localhost:7871"
        task = asyncio.create_task(
            run_first_run_setup(host="localhost", port=7871, env_path=env_path, validate=lambda keys: {})
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            await _wait_ready(base, client)

            resp = await client.get(base + "/")
            assert resp.status_code == 200, resp.status_code
            for name in CLOUD_KEY_FIELDS:
                assert f'name="{name}"' in resp.text, name
            print("OK: GET / -> 200, all three field names present in form HTML")

            resp = await client.post(
                base + "/save",
                data={
                    "DEEPGRAM_API_KEY": "dg-fake-123",
                    "OPENAI_API_KEY": "oa-fake-456",
                    "CARTESIA_API_KEY": "ct-fake-789",
                    "DEMO_LOGIN_EMAIL": "demo@example.com",
                    "DEMO_LOGIN_PASSWORD": "",
                },
            )
            assert resp.status_code == 200, resp.text

        result = await task
        assert result is True, result
        print("OK: POST /save with valid keys completes run_first_run_setup() -> True")

        content = Path(env_path).read_text()
        assert "DEEPGRAM_API_KEY=dg-fake-123" in content
        assert "OPENAI_API_KEY=oa-fake-456" in content
        assert "CARTESIA_API_KEY=ct-fake-789" in content
        assert "DEMO_LOGIN_EMAIL=demo@example.com" in content
        assert "DEMO_TARGET_URL=" in content  # unrelated line preserved from .env.example
        print("OK: .env created from .env.example; key + login lines written; DEMO_TARGET_URL preserved")


async def scenario_preexisting_env_merge() -> None:
    """Step 4: pre-written .env with an existing value + a comment; merge preserves both."""
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("# a hand-written comment\nDEEPGRAM_API_KEY=old\n")
        base = "http://localhost:7872"
        task = asyncio.create_task(
            run_first_run_setup(host="localhost", port=7872, env_path=str(env_path), validate=lambda keys: {})
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            await _wait_ready(base, client)
            resp = await client.post(
                base + "/save",
                data={"DEEPGRAM_API_KEY": "dg-new", "OPENAI_API_KEY": "oa-new", "CARTESIA_API_KEY": "ct-new"},
            )
            assert resp.status_code == 200, resp.text
        assert (await task) is True

        content = env_path.read_text()
        assert "# a hand-written comment\n" in content, content
        assert "DEEPGRAM_API_KEY=dg-new" in content
        assert "DEEPGRAM_API_KEY=old" not in content
        assert "OPENAI_API_KEY=oa-new" in content
        assert "CARTESIA_API_KEY=ct-new" in content
        print("OK: existing value replaced, comment preserved byte-identical, missing vars appended")


class _FlakyValidator:
    """Fails OPENAI_API_KEY exactly once, then passes everything -- lets the
    test drive one error-and-retry cycle against a single running server."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, keys: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"OPENAI_API_KEY": "invalid key"}
        return {}


async def scenario_validation_error_then_ok() -> None:
    """Step 5: first POST fails validation (form re-rendered, task still running);
    second POST with the same values passes once the injected validator flips."""
    with tempfile.TemporaryDirectory() as tmp:
        env_path = str(Path(tmp) / ".env")
        base = "http://localhost:7873"
        validator = _FlakyValidator()
        task = asyncio.create_task(
            run_first_run_setup(host="localhost", port=7873, env_path=env_path, validate=validator)
        )
        payload = {"DEEPGRAM_API_KEY": "dg-1", "OPENAI_API_KEY": "oa-1", "CARTESIA_API_KEY": "ct-1"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            await _wait_ready(base, client)

            resp = await client.post(base + "/save", data=payload)
            assert resp.status_code == 200
            assert "invalid key" in resp.text
            assert 'value="dg-1"' in resp.text  # previously entered values preserved
            assert not task.done(), "task should still be running after a validation error"
            print("OK: validation error -> form re-rendered with error text + preserved values, task still running")

            resp = await client.post(base + "/save", data=payload)
            assert resp.status_code == 200

        result = await task
        assert result is True, result
        print("OK: second POST (validator now ok) completes run_first_run_setup() -> True")


async def scenario_local_mode() -> None:
    """Step 6: POST /local-mode sets PROVIDER_MODE=local and completes True."""
    with tempfile.TemporaryDirectory() as tmp:
        env_path = str(Path(tmp) / ".env")
        base = "http://localhost:7874"
        task = asyncio.create_task(
            run_first_run_setup(host="localhost", port=7874, env_path=env_path, validate=lambda keys: {})
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            await _wait_ready(base, client)
            resp = await client.post(base + "/local-mode")
            assert resp.status_code == 200, resp.text
        assert (await task) is True

        content = Path(env_path).read_text()
        assert "PROVIDER_MODE=local" in content
        print("OK: POST /local-mode -> PROVIDER_MODE=local, completes run_first_run_setup() -> True")


async def main() -> None:
    await scenario_fresh_env_full_save()
    await scenario_preexisting_env_merge()
    await scenario_validation_error_then_ok()
    await scenario_local_mode()
    print("\nSETUP SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
