"""
Pytest fixtures for e2e tests.

Provides Docker Compose management and test utilities.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Generator, AsyncGenerator

import pytest
import httpx


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


def is_docker_compose_running() -> bool:
    """Check if Docker Compose services are already running."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--quiet"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    return bool(result.stdout.strip())


def start_docker_compose() -> None:
    """Start Docker Compose services."""
    print("\n🚀 Starting Docker Compose services...")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def stop_docker_compose() -> None:
    """Stop Docker Compose services."""
    print("\n🛑 Stopping Docker Compose services...")
    subprocess.run(
        ["docker", "compose", "down", "-v"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def wait_for_service(url: str, timeout: int = 60, interval: float = 1.0) -> bool:
    """Wait for a service to become healthy."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(interval)
    return False


def wait_for_websocket(host: str, port: int, timeout: int = 60) -> bool:
    """Wait for WebSocket server to accept connections."""
    import socket

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except (socket.error, OSError):
            pass
        time.sleep(1.0)
    return False


@pytest.fixture(scope="session")
def docker_compose_up():
    """
    Session-scoped fixture that starts Docker Compose before tests
    and stops it after.

    Set E2E_KEEP_RUNNING=1 to keep services running after tests.
    Set E2E_SKIP_STARTUP=1 if services are already running.
    """
    skip_startup = os.environ.get("E2E_SKIP_STARTUP", "").lower() in ("1", "true")
    keep_running = os.environ.get("E2E_KEEP_RUNNING", "").lower() in ("1", "true")

    if not skip_startup:
        # Stop any existing services first
        if is_docker_compose_running():
            stop_docker_compose()

        start_docker_compose()

    yield

    if not keep_running and not skip_startup:
        stop_docker_compose()


@pytest.fixture(scope="session")
def wait_for_services(docker_compose_up) -> dict:
    """
    Wait for all services to become healthy.
    Returns a dict with service URLs.
    """
    services = {
        "web_client": "http://localhost:8000",
        "gateway_ws": "ws://localhost:4000",
        "ray_dashboard": "http://localhost:8265",
    }

    print("\n⏳ Waiting for services to become healthy...")

    # Wait for web client
    if not wait_for_service(f"{services['web_client']}/health", timeout=120):
        pytest.fail("Web client did not become healthy in time")
    print("  ✅ Web client is healthy")

    # Wait for gateway WebSocket
    if not wait_for_websocket("localhost", 4000, timeout=60):
        pytest.fail("Gateway WebSocket is not accepting connections")
    print("  ✅ Gateway WebSocket is ready")

    # Ray dashboard (optional - don't fail if not ready)
    if wait_for_service(f"{services['ray_dashboard']}", timeout=30):
        print("  ✅ Ray Dashboard is healthy")
    else:
        print("  ⚠️ Ray Dashboard not available (non-critical)")

    return services


@pytest.fixture(scope="session")
def web_client_url(wait_for_services) -> str:
    """Get the web client URL."""
    return wait_for_services["web_client"]


@pytest.fixture(scope="session")
def gateway_ws_url(wait_for_services) -> str:
    """Get the gateway WebSocket URL."""
    return wait_for_services["gateway_ws"]


@pytest.fixture
def http_client() -> Generator[httpx.Client, None, None]:
    """Create an HTTP client for tests."""
    with httpx.Client(timeout=10.0) as client:
        yield client


@pytest.fixture
async def async_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an async HTTP client for tests."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


# Mark all tests in this module as e2e
def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: mark test as an end-to-end test")


def pytest_collection_modifyitems(config, items):
    """Auto-mark all tests in tests/e2e as e2e tests."""
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
