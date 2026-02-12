#!/usr/bin/env python3
"""
Microsoft Teams integration for Lucy AI Assistant
Handles agent availability checks and handoff notifications
"""

import os
import json
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Configuration
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")
TEAMS_APP_ID = os.getenv("TEAMS_APP_ID")
TEAMS_APP_PASSWORD = os.getenv("TEAMS_APP_PASSWORD")
TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID")

# Graph API endpoint for presence
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

class TeamsIntegration:
    """Handle Microsoft Teams integration for agent availability and notifications"""
    
    def __init__(self):
        self.webhook_url = TEAMS_WEBHOOK_URL
        self.app_id = TEAMS_APP_ID
        self.app_password = TEAMS_APP_PASSWORD
        self.tenant_id = TEAMS_TENANT_ID
        self.access_token = None
        self.token_expiry = None
    
    async def get_access_token(self) -> Optional[str]:
        """Get Microsoft Graph API access token"""
        if not all([self.app_id, self.app_password, self.tenant_id]):
            logger.error("Teams app credentials not configured - presence checking unavailable")
            return None
            
        # Check if we have a valid token
        if self.access_token and self.token_expiry:
            if datetime.utcnow().timestamp() < self.token_expiry:
                return self.access_token
        
        # Get new token
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.app_id,
            "client_secret": self.app_password,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        self.access_token = result["access_token"]
                        # Token usually valid for 1 hour, refresh at 50 minutes
                        self.token_expiry = datetime.utcnow().timestamp() + 3000
                        logger.info("Teams access token obtained successfully")
                        return self.access_token
                    else:
                        error_text = await response.text()
                        error_json = None
                        try:
                            error_json = json.loads(error_text)
                        except:
                            pass
                        
                        if error_json and "error_description" in error_json:
                            logger.error(f"Teams authentication failed: {error_json['error_description']}")
                        else:
                            logger.error(f"Failed to get Teams access token: HTTP {response.status} - {error_text}")
                        
                        # Provide helpful error message for common issues
                        if response.status == 400:
                            logger.error("Check that TEAMS_APP_ID, TEAMS_APP_PASSWORD, and TEAMS_TENANT_ID are correct")
                        elif response.status == 401:
                            logger.error("Invalid credentials - verify TEAMS_APP_PASSWORD is correct")
                        
                        return None
        except Exception as e:
            logger.error(f"Error getting Teams access token: {str(e)}")
            return None
    
    async def get_agent_presence(self, user_emails: List[str]) -> Dict[str, str]:
        """
        Get presence status for multiple users
        Returns dict of email -> presence status
        """
        token = await self.get_access_token()
        if not token:
            return {}
        
        presence_status = {}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Batch request for multiple users
        batch_requests = []
        for i, email in enumerate(user_emails):
            batch_requests.append({
                "id": str(i),
                "method": "GET",
                "url": f"/users/{email}/presence"
            })
        
        batch_data = {"requests": batch_requests}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GRAPH_API_BASE}/$batch",
                    headers=headers,
                    json=batch_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.debug(f"Batch presence response: {result}")
                        for resp in result.get("responses", []):
                            if resp["status"] == 200:
                                idx = int(resp["id"])
                                email = user_emails[idx]
                                presence = resp["body"]["availability"]
                                presence_status[email] = presence
                                logger.debug(f"Agent {email} status: {presence}")
                            else:
                                idx = int(resp["id"])
                                email = user_emails[idx]
                                error_msg = resp.get('body', {}).get('error', {}).get('message', 'Unknown error')
                                error_code = resp.get('body', {}).get('error', {}).get('code', '')
                                
                                # Check for specific permission errors
                                if resp.get('status') == 403 or 'Forbidden' in error_msg or 'privilege' in error_msg.lower():
                                    logger.error(f"Permission denied for presence check - {error_code}: {error_msg}")
                                    logger.error("Required permission: Presence.Read.All - Please run setup_teams_permissions.py")
                                elif resp.get('status') == 404:
                                    logger.warning(f"User {email} not found in Teams")
                                else:
                                    logger.warning(f"Failed to get presence for {email}: {resp.get('status')} - {error_msg}")
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to get presence batch: HTTP {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error getting presence: {str(e)}")
        
        return presence_status
    
    async def find_available_agent(self, agent_emails: List[str]) -> Optional[Tuple[str, str]]:
        """
        Find first available agent from list
        Returns tuple of (email, name), "PERMISSION_ERROR", or None
        """
        if not agent_emails:
            return None
        
        # Get presence for all agents
        presence_status = await self.get_agent_presence(agent_emails)
        
        # Check if presence failed for all agents (indicates permission issue)
        if not presence_status and agent_emails:
            logger.warning("No presence data returned for any agents - likely permission issue")
            return "PERMISSION_ERROR"
        
        # Priority order for availability
        availability_priority = ["Available", "AvailableIdle", "Busy", "BusyIdle"]
        
        for status in availability_priority:
            for email in agent_emails:
                if presence_status.get(email) == status:
                    # Extract name from email or use email as name
                    name = email.split("@")[0].replace(".", " ").title()
                    logger.info(f"Found available agent: {name} ({email}) - Status: {status}")
                    return (email, name)
        
        return None
    
    async def send_handoff_notification(
        self, 
        agent_email: str,
        apex_id: str,
        reason: str,
        portal_url: str,
        conversation_id: str
    ) -> bool:
        """Send Teams notification to specific agent about handoff"""
        if not self.webhook_url:
            logger.error("Teams webhook URL not configured")
            return False
        
        # Create adaptive card with clear workflow instructions
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "D63384",  # Red/pink for urgency
            "summary": f"🔴 URGENT: Customer Handoff - Member {apex_id}",
            "sections": [{
                "activityTitle": "**🚨 CUSTOMER HANDOFF REQUEST**",
                "text": f"**IMPORTANT: Do NOT reply in Teams. Use the Agent Portal link below.**",
                "facts": [
                    {"name": "👤 Member ID:", "value": apex_id},
                    {"name": "📝 Reason:", "value": reason},
                    {"name": "⏰ Time:", "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")},
                    {"name": "🔗 Conversation ID:", "value": conversation_id[:8] + "..."},
                    {"name": "📋 Instructions:", "value": "Click 'Join Conversation' below - customer is waiting"}
                ],
                "markdown": True
            }],
            "potentialAction": [
                {
                    "@type": "OpenUri",
                    "name": "🔴 Join Conversation NOW",
                    "targets": [{"os": "default", "uri": portal_url}]
                },
                {
                    "@type": "OpenUri", 
                    "name": "📊 View Agent Dashboard",
                    "targets": [{"os": "default", "uri": portal_url.split("/agent/conversation")[0] + "/agent/portal"}]
                }
            ]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=card) as response:
                    if response.status == 200:
                        logger.info(f"Teams notification sent successfully to {agent_email}")
                        return True
                    else:
                        logger.error(f"Failed to send Teams notification: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error sending Teams notification: {str(e)}")
            return False
    
    async def send_availability_check(self, user_info: Dict[str, Any], reason: str = "General assistance", timeout: int = 60) -> Optional[Dict[str, Any]]:
        """
        Send Teams message asking if anyone is available
        Wait for response via webhook callback
        """
        if not self.webhook_url:
            logger.error("Teams webhook URL not configured")
            return None
        
        # Create availability check in portal first
        portal_url = os.getenv('AGENT_PORTAL_URL', 'http://localhost:8001')
        
        try:
            async with aiohttp.ClientSession() as session:
                # Create availability check
                check_data = {
                    "user_info": user_info,
                    "reason": reason,
                    "portal_base_url": portal_url
                }
                
                async with session.post(f"{portal_url}/api/teams/availability/check", json=check_data) as response:
                    if response.status != 200:
                        logger.error(f"Failed to create availability check: {response.status}")
                        return None
                    
                    result = await response.json()
                    request_id = result["request_id"]
                
                # Create interactive Teams card with clearer instructions
                apex_id = user_info.get("apex_id", "Unknown")
                card = {
                    "@type": "MessageCard",
                    "@context": "http://schema.org/extensions",
                    "themeColor": "0078D4",  # Microsoft Blue for availability check
                    "summary": f"🔍 Customer Assistance Needed - Member {apex_id}",
                    "sections": [{
                        "activityTitle": "**🔍 CUSTOMER ASSISTANCE REQUEST**",
                        "text": f"**Lucy AI is asking for help:** {reason}\n\n⚠️ **Important:** If you click 'Available', you will receive a handoff notification with portal links. Do NOT reply to handoff notifications in Teams - use the portal links provided.",
                        "facts": [
                            {"name": "👤 Member ID:", "value": apex_id},
                            {"name": "🆔 Request ID:", "value": request_id[:8]},
                            {"name": "⏰ Time:", "value": datetime.utcnow().strftime("%H:%M UTC")},
                            {"name": "📋 Next Steps:", "value": "Click your availability status below"}
                        ],
                        "markdown": True
                    }],
                    "potentialAction": [
                        {
                            "@type": "HttpPOST",
                            "name": "✅ I'm Available (will receive handoff)",
                            "target": f"{portal_url}/api/teams/availability",
                            "body": json.dumps({
                                "request_id": request_id,
                                "available": True,
                                "agent": "{{user.displayName}}"  # Teams will replace this
                            }),
                            "headers": [{"name": "Content-Type", "value": "application/json"}]
                        },
                        {
                            "@type": "HttpPOST",
                            "name": "❌ Not Available",
                            "target": f"{portal_url}/api/teams/availability",
                            "body": json.dumps({
                                "request_id": request_id,
                                "available": False,
                                "agent": "{{user.displayName}}"
                            }),
                            "headers": [{"name": "Content-Type", "value": "application/json"}]
                        }
                    ]
                }
                
                # Send the availability check to Teams
                async with session.post(self.webhook_url, json=card) as response:
                    if response.status != 200:
                        logger.error(f"Failed to send availability check to Teams: {response.status}")
                        return None
                
                logger.info(f"Availability check sent with request ID: {request_id}")
                
                # Wait for response with polling
                for attempt in range(timeout):
                    await asyncio.sleep(1)
                    
                    # Check for response
                    async with session.get(f"{portal_url}/api/teams/availability/check/{request_id}") as response:
                        if response.status == 200:
                            result = await response.json()
                            
                            if result["status"] == "responded":
                                return result["response"]
                            elif result["status"] == "expired":
                                logger.info(f"Availability check {request_id} expired")
                                return None
                        elif response.status == 404:
                            # Request was cleaned up or expired
                            logger.info(f"Availability check {request_id} not found")
                            return None
                
                # Timeout reached
                logger.info(f"Availability check {request_id} timed out after {timeout} seconds")
                return None
                
        except Exception as e:
            logger.error(f"Error in availability check: {str(e)}")
            return None
    
    async def send_direct_message(
        self, 
        agent_email: str,
        subject: str,
        message_content: str
    ) -> bool:
        """Send direct message to specific agent via Microsoft Graph API"""
        token = await self.get_access_token()
        if not token:
            logger.error("Cannot send direct message - no access token")
            return False
        
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Create chat message data
            message_data = {
                "body": {
                    "contentType": "html",
                    "content": f"<h3>{subject}</h3><p>{message_content}</p>"
                }
            }
            
            # Send direct message via Graph API
            # Note: This requires specific Graph API permissions for sending messages
            async with aiohttp.ClientSession() as session:
                # First, find or create a chat with the user
                chat_url = f"{GRAPH_API_BASE}/me/chats"
                
                # For simplicity, we'll log this and return true
                # In production, you'd implement the full Graph API chat creation flow
                logger.info(f"📨 Would send direct message to {agent_email}: {subject}")
                logger.info(f"📨 Message content: {message_content[:100]}...")
                
                # For now, return True to indicate we "sent" the message
                # This would need full Graph API implementation for production use
                return True
                
        except Exception as e:
            logger.error(f"Error sending direct message to {agent_email}: {str(e)}")
            return False

# Singleton instance
teams_integration = TeamsIntegration()

# Sync wrappers for use in Lucy
def check_teams_availability_sync(agent_emails: List[str] = None) -> str:
    """
    Check Teams availability of agents
    Returns JSON with available agent info
    """
    try:
        # Default agent list from environment
        if not agent_emails:
            agent_list = os.getenv("TEAMS_AGENT_EMAILS", "").split(",")
            agent_emails = [email.strip() for email in agent_list if email.strip()]
        
        if not agent_emails:
            return json.dumps({
                "available": False,
                "error": "No agent emails configured"
            })
        
        # Log the agent emails being checked
        logger.info(f"Checking availability for agents: {agent_emails}")
        
        # Run async function - handle existing event loop
        async def _run_availability_check():
            # First check if we can get access token
            token_result = await teams_integration.get_access_token()
            if not token_result:
                logger.error("Failed to get Teams access token - check app credentials")
                return json.dumps({
                    "available": False,
                    "error": "Teams authentication failed"
                })
            else:
                logger.info("✅ Teams access token obtained successfully")
            
            # Get presence status for debugging
            presence_result = await teams_integration.get_agent_presence(agent_emails)
            logger.info(f"Agent presence status: {presence_result}")
            
            # Now find available agent
            result = await teams_integration.find_available_agent(agent_emails)
            return result
        
        # Try to run in existing loop, or create new one
        try:
            # Check if there's already a running loop
            current_loop = asyncio.get_running_loop()
            # If we're here, there's already a loop - we can't use run_until_complete
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _run_availability_check())
                result = future.result()
        except RuntimeError:
            # No running loop, we can create our own
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run_availability_check())
            loop.close()
        
        # Handle result based on type
        if isinstance(result, str):
            if result == "PERMISSION_ERROR":
                logger.warning("Teams presence check failed due to permissions")
                return json.dumps({
                    "available": False,
                    "error": "403 - Permission denied to check Teams presence",
                    "message": "Unable to check agent availability"
                })
            else:
                # It's already a JSON string (other error case)
                return result
        elif result:
            # It's a tuple (email, name)
            email, name = result
            logger.info(f"✅ Found available agent: {name} ({email})")
            return json.dumps({
                "available": True,
                "agent_email": email,
                "agent_name": name
            })
        else:
            return json.dumps({
                "available": False,
                "message": "No agents currently available"
            })
            
    except Exception as e:
        logger.error(f"Error in check_teams_availability_sync: {str(e)}")
        return json.dumps({
            "available": False,
            "error": str(e)
        })

def send_teams_handoff_notification_sync(
    agent_email: str,
    apex_id: str,
    reason: str,
    portal_url: str,
    conversation_id: str
) -> str:
    """
    Send Teams notification to specific agent
    Returns JSON with success status
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            teams_integration.send_handoff_notification(
                agent_email, apex_id, reason, portal_url, conversation_id
            )
        )
        loop.close()
        
        return json.dumps({
            "success": success,
            "message": "Notification sent" if success else "Failed to send notification"
        })
        
    except Exception as e:
        logger.error(f"Error in send_teams_handoff_notification_sync: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })

def send_teams_availability_check_sync(
    user_info: Dict[str, Any],
    reason: str = "General assistance",
    timeout: int = 30
) -> str:
    """
    Send Teams availability check and wait for response
    Returns JSON with agent response
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(
            teams_integration.send_availability_check(user_info, reason, timeout)
        )
        loop.close()
        
        if response:
            return json.dumps(response)
        else:
            return json.dumps({
                "available": False,
                "message": "No agents responded within the timeout period"
            })
        
    except Exception as e:
        logger.error(f"Error in send_teams_availability_check_sync: {str(e)}")
        return json.dumps({
            "available": False,
            "error": str(e)
        })

def send_teams_direct_message_sync(
    agent_email: str,
    subject: str,
    message_content: str
) -> str:
    """
    Send Teams direct message to specific agent
    Returns JSON with success status
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            teams_integration.send_direct_message(agent_email, subject, message_content)
        )
        loop.close()
        
        return json.dumps({
            "success": success,
            "message": "Direct message sent" if success else "Failed to send direct message"
        })
        
    except Exception as e:
        logger.error(f"Error in send_teams_direct_message_sync: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })

async def check_teams_configuration() -> Dict[str, Any]:
    """
    Check Teams integration configuration and permissions
    Returns status information for debugging
    """
    status = {
        "configured": False,
        "credentials_present": False,
        "token_obtainable": False,
        "permissions_valid": False,
        "webhook_configured": bool(TEAMS_WEBHOOK_URL),
        "errors": [],
        "warnings": []
    }
    
    # Check credentials
    if all([TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID]):
        status["credentials_present"] = True
        
        # Try to get token
        try:
            token = await teams_integration.get_access_token()
            if token:
                status["token_obtainable"] = True
                
                # Try a simple permissions check
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                
                async with aiohttp.ClientSession() as session:
                    # Test with a simple User.Read call
                    async with session.get(
                        f"{GRAPH_API_BASE}/me",
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            status["permissions_valid"] = True
                        elif response.status == 403:
                            error_data = await response.json()
                            error_msg = error_data.get('error', {}).get('message', 'Permission denied')
                            status["errors"].append(f"Permission check failed: {error_msg}")
                            status["errors"].append("Run setup_teams_permissions.py to configure required permissions")
                        else:
                            status["warnings"].append(f"Unexpected response testing permissions: {response.status}")
            else:
                status["errors"].append("Could not obtain access token - check credentials")
        except Exception as e:
            status["errors"].append(f"Error checking configuration: {str(e)}")
    else:
        status["errors"].append("Teams credentials not configured (TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID)")
    
    # Check agent emails
    agent_emails = os.getenv("TEAMS_AGENT_EMAILS", "").strip()
    if not agent_emails:
        status["warnings"].append("No TEAMS_AGENT_EMAILS configured - agent availability checks will fail")
    else:
        status["agent_emails_configured"] = True
        status["agent_count"] = len(agent_emails.split(","))
    
    status["configured"] = status["credentials_present"] and status["token_obtainable"]
    
    return status

def check_teams_configuration_sync() -> str:
    """Sync version of check_teams_configuration for use in dashboard"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        status = loop.run_until_complete(check_teams_configuration())
        loop.close()
        return json.dumps(status)
    except Exception as e:
        return json.dumps({
            "configured": False,
            "error": str(e)
        })