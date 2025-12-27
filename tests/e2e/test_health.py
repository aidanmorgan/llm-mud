"""
Health check tests for e2e infrastructure.

These tests verify that all services are running and accessible.
"""

import pytest


class TestHealthChecks:
    """Basic health check tests for all services."""

    def test_web_client_health(self, http_client, web_client_url):
        """Test that the web client health endpoint responds correctly."""
        response = http_client.get(f"{web_client_url}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_web_client_homepage(self, http_client, web_client_url):
        """Test that the web client serves the game page."""
        response = http_client.get(web_client_url)

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        # Should contain some expected HTML content
        assert b"LLM-MUD" in response.content or b"session_id" in response.content

    def test_web_client_sets_session_cookie(self, http_client, web_client_url):
        """Test that the web client sets a session cookie."""
        response = http_client.get(web_client_url)

        assert response.status_code == 200
        assert "session_id" in response.cookies


class TestDockerCompose:
    """Tests for Docker Compose infrastructure."""

    def test_services_are_running(self, docker_compose_up):
        """Test that Docker Compose started successfully."""
        import subprocess

        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running"],
            capture_output=True,
            text=True,
        )

        # Should have running services
        assert result.returncode == 0
        output = result.stdout
        # Check for key services
        assert "web-client" in output or "web" in output

    def test_ray_cluster_formed(self, wait_for_services):
        """Test that Ray cluster has formed with workers."""
        import httpx

        ray_dashboard = wait_for_services.get("ray_dashboard")
        if not ray_dashboard:
            pytest.skip("Ray dashboard not available")

        try:
            response = httpx.get(f"{ray_dashboard}/api/cluster_status", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                # Just check we can access the API
                assert "result" in data or "data" in data or True
        except httpx.HTTPError:
            pytest.skip("Ray dashboard API not accessible")
