#!/usr/bin/env python3
"""Unit tests for Tesla API client."""

import json
import os
import time
from unittest.mock import Mock, patch

import pytest

from Tesla.tesla_client import (
    TeslaAPIClient,
    BatteryProduct,
    TeslaAuthError,
    TeslaTokenExpiredError,
    TeslaAPIError,
)


@pytest.fixture
def mock_tokens():
    """Generate mock tokens."""
    return {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
        "created_at": int(time.time()),
    }


@pytest.fixture
def temp_token_file(tmp_path):
    """Create temporary token file."""
    token_file = tmp_path / "tesla_tokens.json"
    return str(token_file)


@pytest.fixture
def client_with_tokens(temp_token_file, mock_tokens):
    """Create client with pre-saved tokens."""
    os.makedirs(os.path.dirname(temp_token_file), exist_ok=True)
    with open(temp_token_file, "w") as f:
        json.dump(mock_tokens, f)
    os.chmod(temp_token_file, 0o600)
    return TeslaAPIClient(token_file=temp_token_file)


class TestTeslaAPIClient:
    """Tests for TeslaAPIClient."""

    def test_load_tokens_success(self, client_with_tokens, mock_tokens):
        """Test successful token loading."""
        tokens = client_with_tokens._load_tokens()
        assert tokens["access_token"] == mock_tokens["access_token"]
        assert tokens["refresh_token"] == mock_tokens["refresh_token"]

    def test_load_tokens_file_not_found(self, temp_token_file):
        """Test token loading with missing file."""
        client = TeslaAPIClient(token_file=temp_token_file)
        with pytest.raises(TeslaTokenExpiredError, match="Token file not found"):
            client._load_tokens()

    def test_load_tokens_invalid_json(self, temp_token_file):
        """Test token loading with invalid JSON."""
        with open(temp_token_file, "w") as f:
            f.write("invalid json{")

        client = TeslaAPIClient(token_file=temp_token_file)
        with pytest.raises(TeslaAuthError, match="Invalid token file format"):
            client._load_tokens()

    def test_save_tokens(self, temp_token_file, mock_tokens):
        """Test token saving with proper permissions."""
        client = TeslaAPIClient(token_file=temp_token_file)
        client._save_tokens(mock_tokens)

        # Verify file exists and has correct permissions
        assert os.path.exists(temp_token_file)
        assert oct(os.stat(temp_token_file).st_mode)[-3:] == "600"

        # Verify content
        with open(temp_token_file) as f:
            saved_tokens = json.load(f)
        assert saved_tokens["access_token"] == mock_tokens["access_token"]

    def test_is_token_expired_fresh(self, client_with_tokens, mock_tokens):
        """Test token expiry detection with fresh token."""
        client_with_tokens._tokens = mock_tokens
        assert not client_with_tokens._is_token_expired()

    def test_is_token_expired_soon(self, client_with_tokens):
        """Test token expiry detection with expiring soon token."""
        client_with_tokens._tokens = {
            "expires_at": int(time.time()) + 200,  # Less than 5min buffer
        }
        assert client_with_tokens._is_token_expired()

    def test_is_token_expired_past(self, client_with_tokens):
        """Test token expiry detection with expired token."""
        client_with_tokens._tokens = {
            "expires_at": int(time.time()) - 100,
        }
        assert client_with_tokens._is_token_expired()

    @patch("requests.Session.post")
    def test_refresh_access_token_success(self, mock_post, client_with_tokens, mock_tokens):
        """Test successful token refresh."""
        # Mock refresh response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        client_with_tokens._refresh_access_token()

        # Verify token was updated
        assert client_with_tokens._tokens["access_token"] == "new_access_token"
        assert "expires_at" in client_with_tokens._tokens

    @patch("requests.Session.post")
    def test_refresh_access_token_invalid_refresh_token(
        self, mock_post, client_with_tokens, mock_tokens
    ):
        """Test token refresh with invalid refresh token."""
        import requests

        mock_response = Mock()
        mock_response.status_code = 400
        http_error = requests.HTTPError("Bad Request")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_post.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        with pytest.raises(TeslaTokenExpiredError, match="Refresh token invalid"):
            client_with_tokens._refresh_access_token()

    @patch("requests.Session.request")
    def test_get_energy_sites_success(self, mock_request, client_with_tokens, mock_tokens):
        """Test getting energy sites."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": [
                {"resource_type": "battery", "energy_site_id": 123, "site_name": "Home"},
                {"resource_type": "solar", "energy_site_id": 456},
            ]
        }
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        sites = client_with_tokens.get_energy_sites()

        assert len(sites) == 1
        assert sites[0]["energy_site_id"] == 123
        assert sites[0]["resource_type"] == "battery"

    @patch("requests.Session.request")
    def test_get_site_info(self, mock_request, client_with_tokens, mock_tokens):
        """Test getting site info."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {
                "site_name": "Home Battery",
                "components": {"battery": True},
            }
        }
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        info = client_with_tokens.get_site_info(123)

        assert info["site_name"] == "Home Battery"
        assert "components" in info

    @patch("requests.Session.request")
    def test_get_site_data(self, mock_request, client_with_tokens, mock_tokens):
        """Test getting site data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {
                "percentage_charged": 75.5,
                "battery_power": -1500,
            }
        }
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        data = client_with_tokens.get_site_data(123)

        assert data["percentage_charged"] == 75.5
        assert data["battery_power"] == -1500

    @patch("requests.Session.request")
    def test_set_operation_mode(self, mock_request, client_with_tokens, mock_tokens):
        """Test setting operation mode."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"message": "Updated"}}
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        result = client_with_tokens.set_operation_mode(123, "self_consumption")

        assert result == "Updated"
        # Verify request was made correctly
        call_args = mock_request.call_args
        assert "operation" in call_args[0][1]
        assert call_args[1]["json"]["default_real_mode"] == "self_consumption"

    @patch("requests.Session.request")
    def test_set_backup_reserve(self, mock_request, client_with_tokens, mock_tokens):
        """Test setting backup reserve."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"message": "Updated"}}
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        result = client_with_tokens.set_backup_reserve(123, 80)

        assert result == "Updated"
        # Verify request was made correctly
        call_args = mock_request.call_args
        assert "backup" in call_args[0][1]
        assert call_args[1]["json"]["backup_reserve_percent"] == 80

    @patch("requests.Session.request")
    def test_request_401_retry(self, mock_request, client_with_tokens, mock_tokens):
        """Test automatic retry on 401."""
        # First request returns 401, second succeeds
        mock_response_401 = Mock()
        mock_response_401.status_code = 401
        mock_response_401.raise_for_status.side_effect = Exception("401")

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"response": []}

        mock_request.side_effect = [mock_response_401, mock_response_success]

        client_with_tokens._tokens = mock_tokens

        with patch.object(client_with_tokens, "_refresh_access_token"):
            result = client_with_tokens._request("GET", "api/1/products")
            assert result == {"response": []}

    @patch("requests.Session.request")
    def test_request_rate_limit(self, mock_request, client_with_tokens, mock_tokens):
        """Test rate limit error handling."""
        import requests

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"
        http_error = requests.HTTPError("Rate limited")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_request.return_value = mock_response

        client_with_tokens._tokens = mock_tokens
        with pytest.raises(TeslaAPIError, match="Rate limited"):
            client_with_tokens._request("GET", "api/1/products")

    @patch("requests.Session.request")
    def test_request_timeout(self, mock_request, client_with_tokens, mock_tokens):
        """Test timeout error handling."""
        import requests

        mock_request.side_effect = requests.Timeout("Connection timeout")

        client_with_tokens._tokens = mock_tokens
        with pytest.raises(TeslaAPIError, match="Request timeout"):
            client_with_tokens._request("GET", "api/1/products")


class TestBatteryProduct:
    """Tests for BatteryProduct wrapper."""

    @pytest.fixture
    def mock_client(self):
        """Create mock client."""
        return Mock(spec=TeslaAPIClient)

    @pytest.fixture
    def mock_site_data(self):
        """Create mock site data."""
        return {
            "energy_site_id": 123,
            "site_name": "Home",
            "percentage_charged": 75.5,
            "backup_reserve_percent": 20,
        }

    def test_init(self, mock_client, mock_site_data):
        """Test BatteryProduct initialization."""
        product = BatteryProduct(mock_site_data, mock_client)
        assert product.site_id == 123
        assert product._client == mock_client
        assert product._data == mock_site_data

    def test_getitem(self, mock_client, mock_site_data):
        """Test dict-like item access."""
        product = BatteryProduct(mock_site_data, mock_client)
        assert product["site_name"] == "Home"
        assert product["percentage_charged"] == 75.5

    def test_get_method(self, mock_client, mock_site_data):
        """Test dict-like get method."""
        product = BatteryProduct(mock_site_data, mock_client)
        assert product.get("site_name") == "Home"
        assert product.get("nonexistent", "default") == "default"

    def test_get_site_info(self, mock_client, mock_site_data):
        """Test get_site_info updates data."""
        mock_client.get_site_info.return_value = {"new_field": "new_value"}

        product = BatteryProduct(mock_site_data, mock_client)
        result = product.get_site_info()

        mock_client.get_site_info.assert_called_once_with(123)
        assert "new_field" in product._data
        assert result == product

    def test_get_site_data(self, mock_client, mock_site_data):
        """Test get_site_data updates data."""
        mock_client.get_site_data.return_value = {"battery_power": -1500}

        product = BatteryProduct(mock_site_data, mock_client)
        result = product.get_site_data()

        mock_client.get_site_data.assert_called_once_with(123)
        assert "battery_power" in product._data
        assert result == product

    def test_set_operation(self, mock_client, mock_site_data):
        """Test set_operation delegates to client."""
        mock_client.set_operation_mode.return_value = "Updated"

        product = BatteryProduct(mock_site_data, mock_client)
        result = product.set_operation("autonomous")

        mock_client.set_operation_mode.assert_called_once_with(123, "autonomous")
        assert result == "Updated"

    def test_set_backup_reserve_percent(self, mock_client, mock_site_data):
        """Test set_backup_reserve_percent delegates to client."""
        mock_client.set_backup_reserve.return_value = "Updated"

        product = BatteryProduct(mock_site_data, mock_client)
        result = product.set_backup_reserve_percent(80)

        mock_client.set_backup_reserve.assert_called_once_with(123, 80)
        assert result == "Updated"
