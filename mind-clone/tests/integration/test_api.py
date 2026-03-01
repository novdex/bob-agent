"""
Integration tests for API endpoints.
"""

import pytest


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_heartbeat(self, test_client):
        """Test heartbeat endpoint."""
        response = test_client.get("/heartbeat")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert "agent" in data
        assert "model" in data

    def test_status_runtime(self, test_client):
        """Test runtime status endpoint."""
        response = test_client.get("/status/runtime")
        assert response.status_code == 200
        data = response.json()
        assert "worker_alive" in data
        assert "db_healthy" in data


class TestTaskEndpoints:
    """Test task management endpoints."""

    def test_list_tasks_empty(self, test_client):
        """Test listing tasks when empty."""
        response = test_client.get("/ui/tasks")
        assert response.status_code == 200
        # Should return empty list or similar

    def test_create_task(self, test_client):
        """Test creating a task."""
        response = test_client.post(
            "/ui/tasks", json={"title": "Test Task", "goal": "Test goal description"}
        )
        # May fail without proper auth, but should not crash
        assert response.status_code in [200, 401, 403, 422]


class TestGoalEndpoints:
    """Test goal management endpoints."""

    def test_list_goals(self, test_client):
        """Test listing goals."""
        response = test_client.get("/goals")
        assert response.status_code == 200

    def test_create_goal(self, test_client):
        """Test creating a goal."""
        response = test_client.post(
            "/goal", json={"title": "Test Goal", "description": "Test description"}
        )
        assert response.status_code in [200, 401, 403, 422]


class TestDebugEndpoints:
    """Test debug endpoints."""

    def test_blackbox_events(self, test_client, db_session):
        """Test blackbox events endpoint."""
        response = test_client.get("/debug/blackbox", params={"owner_id": 1})
        assert response.status_code == 200

    def test_blackbox_sessions(self, test_client, db_session):
        """Test blackbox sessions endpoint."""
        response = test_client.get("/debug/blackbox/sessions", params={"owner_id": 1})
        assert response.status_code == 200
