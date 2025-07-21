import base64
import json
import logging
import os
import urllib.parse
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

OAUTH_CONFIG = {
    "tenant_id": "common",
    "redirect_uri": "http://localhost:8080/callback",
    "scopes": [
        "https://outlook.office365.com/IMAP.AccessAsUser.All",
        "offline_access"
    ],
    "client_credentials_scope": "https://outlook.office365.com/.default"
}

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    authorization_code = None
    
    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == '/callback':
            query_params = parse_qs(parsed_url.query)
            if 'code' in query_params:
                OAuthCallbackHandler.authorization_code = query_params['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authorization Successful!</h1><p>You can close this window now.</p></body></html>')
                console.print("[green]Authorization code received successfully![/green]")
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authorization Failed!</h1><p>No authorization code received.</p></body></html>')
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1>404 Not Found</h1></body></html>')
    
    def log_message(self, format, *args):
        pass

class OAuth2Manager:
    def __init__(self, client_id: str, client_secret: str, tenant_id: str = "common", tokens_dir: Optional[Path] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.tokens = {}
        self.tokens_file = tokens_dir / "oauth_tokens.json" if tokens_dir else Path("tokens/oauth_tokens.json")
        self.load_tokens()
    
    def load_tokens(self):
        try:
            if self.tokens_file.exists():
                with open(self.tokens_file, 'r') as f:
                    self.tokens = json.load(f)
                logger.info("Loaded existing OAuth tokens")
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")
            self.tokens = {}
    
    def save_tokens(self):
        try:
            with open(self.tokens_file, 'w') as f:
                json.dump(self.tokens, f, indent=2)
            os.chmod(self.tokens_file, 0o600)
            logger.info("OAuth tokens saved")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")
    
    def get_authorization_url(self) -> str:
        scope_string = " ".join(OAUTH_CONFIG["scopes"])
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': OAUTH_CONFIG["redirect_uri"],
            'scope': scope_string,
            'response_mode': 'query'
        }
        auth_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        return f"{auth_url}?{urllib.parse.urlencode(params)}"
    
    def exchange_code_for_tokens(self, authorization_code: str) -> bool:
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': authorization_code,
            'redirect_uri': OAUTH_CONFIG["redirect_uri"],
            'grant_type': 'authorization_code',
            'scope': ' '.join(OAUTH_CONFIG["scopes"])
        }
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.tokens = {
                'access_token': token_data['access_token'],
                'refresh_token': token_data['refresh_token'],
                'expires_at': (datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600) - 300)).isoformat()
            }
            self.save_tokens()
            logger.info("Successfully obtained OAuth tokens")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Error exchanging authorization code: {e}")
            return False
    
    def refresh_token(self) -> bool:
        if not self.tokens.get('refresh_token'):
            return False
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.tokens['refresh_token'],
            'grant_type': 'refresh_token',
            'scope': ' '.join(OAUTH_CONFIG["scopes"])
        }
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.tokens['access_token'] = token_data['access_token']
            if 'refresh_token' in token_data:
                self.tokens['refresh_token'] = token_data['refresh_token']
            self.tokens['expires_at'] = (datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600) - 300)).isoformat()
            self.save_tokens()
            logger.info("OAuth token refreshed successfully")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Error refreshing token: {e}")
            return False
    
    def get_valid_token(self) -> Optional[str]:
        if not self.tokens.get('access_token') or not self.tokens.get('expires_at'):
            logger.warning("No access token or expiration time found")
            return None
        
        try:
            expires_at = datetime.fromisoformat(self.tokens['expires_at'])
        except ValueError as e:
            logger.error(f"Invalid expires_at format: {e}")
            return None
            
        # Refresh token if it expires within 10 minutes (more conservative)
        if datetime.now() >= expires_at - timedelta(minutes=10):
            logger.info("Token expires soon, refreshing...")
            # Check if this is a client credentials token (no refresh token)
            if self.tokens.get('grant_type') == 'client_credentials':
                if not self.refresh_client_credentials_token():
                    logger.error("Failed to refresh client credentials token")
                    return None
            else:
                # Standard refresh token flow
                if not self.refresh_token():
                    logger.error("Failed to refresh token")
                    return None
        
        return self.tokens['access_token']
    
    def generate_xoauth2_string(self, username: str, access_token: str) -> str:
        auth_string = f"user={username}\x01auth=Bearer {access_token}\x01\x01"
        return base64.b64encode(auth_string.encode()).decode()
    
    def get_xoauth2_for_user(self, username: str) -> Optional[str]:
        token = self.get_valid_token()
        if not token:
            return None
        return self.generate_xoauth2_string(username, token)
    
    def acquire_token(self) -> bool:
        """Acquire token using client credentials flow for application permissions"""
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': OAUTH_CONFIG["client_credentials_scope"],
            'grant_type': 'client_credentials'
        }
        
        try:
            logger.info("Requesting access token using client credentials flow...")
            response = requests.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            # Store the token
            self.tokens = {
                'access_token': token_data['access_token'],
                'token_type': token_data.get('token_type', 'Bearer'),
                'expires_at': (datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600) - 300)).isoformat(),
                'grant_type': 'client_credentials'
            }
            self.save_tokens()
            logger.info("Successfully obtained client credentials token")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error acquiring client credentials token: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"Error details: {error_detail}")
                except:
                    logger.error(f"Response: {e.response.text}")
            return False
    
    def refresh_client_credentials_token(self) -> bool:
        """Refresh client credentials token (essentially re-acquire it)"""
        logger.info("Refreshing client credentials token...")
        return self.acquire_token()
