#!/usr/bin/env python3
"""
Fallback Teams integration module for deployments where full Teams integration is not available.
This provides stub functions that gracefully handle the absence of Teams integration.
"""

import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def check_teams_availability_sync(agent_emails: List[str] = None) -> str:
    """
    Fallback function for checking Teams availability when full Teams integration is not available.
    Returns a standard "not available" response.
    """
    logger.info("Using fallback Teams availability check - Teams integration not fully configured")
    
    return json.dumps({
        "available": False,
        "message": "Teams integration not configured - using email fallback",
        "fallback_mode": True
    })

def send_teams_handoff_notification_sync(
    agent_email: str,
    apex_id: str,
    reason: str,
    portal_url: str,
    conversation_id: str
) -> str:
    """
    Fallback function for sending Teams notifications when full Teams integration is not available.
    Returns a standard "not available" response.
    """
    logger.info(f"Using fallback Teams notification - would notify {agent_email} about {apex_id}")
    
    return json.dumps({
        "success": False,
        "message": "Teams notification not available - using email fallback",
        "fallback_mode": True
    })

def send_teams_direct_message_sync(
    agent_email: str,
    subject: str,
    message_content: str
) -> str:
    """
    Fallback function for sending direct Teams messages when full Teams integration is not available.
    Returns a standard "not available" response.
    """
    logger.info(f"Using fallback Teams direct message - would message {agent_email}: {subject}")
    
    return json.dumps({
        "success": False,
        "message": "Teams direct messaging not available",
        "fallback_mode": True
    })

def send_teams_availability_check_sync(
    user_info: Dict[str, Any],
    reason: str = "General assistance",
    timeout: int = 30
) -> str:
    """
    Fallback function for Teams availability checks when full Teams integration is not available.
    Returns a standard "not available" response.
    """
    logger.info(f"Using fallback Teams availability check for {user_info.get('apex_id', 'unknown')}")
    
    return json.dumps({
        "available": False,
        "message": "Teams availability check not configured",
        "fallback_mode": True
    })