"""
Conversation Summarizer for Customer Service Insights
Generates concise, data-rich summaries for agent portal Member Notes
"""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import requests

logger = logging.getLogger(__name__)

class ConversationSummarizer:
    """Generate insightful customer service summaries from conversation history"""
    
    def __init__(self):
        self.azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_openai_key = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        self.model = os.getenv("AZURE_SUMMARY_MODEL") or os.getenv("AZURE_GPT_MODEL", "gpt-4o")
        
    def generate_summary(self, messages: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate a concise customer service summary from conversation messages
        
        Args:
            messages: List of conversation messages with role, content, timestamp
            metadata: Optional metadata about the conversation (apex_id, reason, etc.)
            
        Returns:
            Concise summary for Member Notes
        """
        try:
            # If no AI configured, use template-based summary
            if not self.azure_openai_endpoint or not self.azure_openai_key:
                return self._generate_template_summary(messages, metadata)
            
            # Prepare conversation for AI summarization
            conversation_text = self._format_conversation(messages)
            
            # Create the prompt for customer service summary
            prompt = f"""Analyze this customer service conversation and create a concise summary for the Member Notes section.

Focus on:
1. Primary issue/request
2. Key information discovered
3. Actions taken or recommended
4. Resolution status
5. Any follow-up needed

Keep it under 150 words, professional, and data-rich for future analytics.

Conversation:
{conversation_text}

Member ID: {metadata.get('apex_id', 'Unknown') if metadata else 'Unknown'}
Reason for contact: {metadata.get('handoff_reason', 'Not specified') if metadata else 'Not specified'}

Summary:"""

            # Call Azure OpenAI
            headers = {
                "api-key": self.azure_openai_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "messages": [
                    {"role": "system", "content": "You are a customer service analyst creating concise, insightful summaries for case management."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 200,
                "temperature": 0.3,  # Lower temperature for consistent summaries
                "model": self.model
            }
            
            response = requests.post(
                f"{self.azure_openai_endpoint}/openai/deployments/{self.model}/chat/completions?api-version=2024-02-01",
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                summary = result['choices'][0]['message']['content'].strip()
                return summary
            else:
                logger.error(f"AI summary failed: {response.status_code} - {response.text}")
                return self._generate_template_summary(messages, metadata)
                
        except Exception as e:
            logger.error(f"Error generating AI summary: {e}")
            return self._generate_template_summary(messages, metadata)
    
    def _format_conversation(self, messages: List[Dict[str, Any]]) -> str:
        """Format messages into readable conversation text"""
        formatted_lines = []
        
        for msg in messages:
            role = msg.get('role', 'Unknown')
            content = msg.get('content', '')
            
            # Clean up content
            content = content.strip()
            if len(content) > 500:  # Truncate very long messages
                content = content[:497] + "..."
            
            formatted_lines.append(f"{role}: {content}")
        
        return "\n\n".join(formatted_lines)
    
    def _generate_template_summary(self, messages: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
        """Generate a template-based summary when AI is not available"""
        
        # Extract key information from messages
        user_messages = [m for m in messages if m.get('role') == 'User']
        lucy_messages = [m for m in messages if m.get('role') == 'Lucy']
        
        # Find key topics discussed
        topics = []
        keywords = ['settlement', 'payment', 'check', 'address', 'status', 'documents', 'eligibility']
        
        all_content = ' '.join([m.get('content', '').lower() for m in messages])
        
        for keyword in keywords:
            if keyword in all_content:
                topics.append(keyword)
        
        # Determine if authenticated
        apex_id = metadata.get('apex_id', 'UNKNOWN') if metadata else 'UNKNOWN'
        authenticated = apex_id != 'UNKNOWN'
        
        # Build summary
        summary_parts = []
        
        # Opening
        if authenticated:
            summary_parts.append(f"Member {apex_id} contacted support")
        else:
            summary_parts.append("Unauthenticated user contacted support")
        
        # Reason
        if metadata and metadata.get('handoff_reason'):
            reason = metadata['handoff_reason']
            if len(reason) > 100:
                reason = reason[:97] + "..."
            summary_parts.append(f"regarding: {reason}")
        elif topics:
            summary_parts.append(f"regarding: {', '.join(topics[:3])}")
        
        # Message count and escalation
        summary_parts.append(f"After {len(messages)} exchanges, escalated to human agent.")
        
        # Add standard closing
        summary_parts.append("Awaiting agent intervention for resolution.")
        
        return " ".join(summary_parts)
    
    def extract_key_data_points(self, messages: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract structured data points for analytics"""
        
        data_points = {
            "authenticated": metadata.get('apex_id', 'UNKNOWN') != 'UNKNOWN' if metadata else False,
            "message_count": len(messages),
            "escalation_reason": metadata.get('handoff_reason', 'Not specified') if metadata else 'Not specified',
            "topics_discussed": [],
            "actions_requested": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Extract topics and actions from conversation
        all_content = ' '.join([m.get('content', '').lower() for m in messages])
        
        # Topics
        topic_keywords = {
            'payment': ['payment', 'check', 'money', 'amount'],
            'address': ['address', 'update', 'change', 'move'],
            'documents': ['document', 'notice', 'pdf', 'letter'],
            'status': ['status', 'eligibility', 'approved', 'denied'],
            'timeline': ['when', 'timeline', 'date', 'how long']
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in all_content for kw in keywords):
                data_points['topics_discussed'].append(topic)
        
        # Actions
        action_keywords = {
            'update_info': ['update', 'change', 'modify'],
            'check_status': ['status', 'check', 'verify'],
            'reissue': ['reissue', 'resend', 'new check'],
            'callback': ['call back', 'callback', 'phone'],
            'human_help': ['human', 'agent', 'representative', 'help']
        }
        
        for action, keywords in action_keywords.items():
            if any(kw in all_content for kw in keywords):
                data_points['actions_requested'].append(action)
        
        return data_points

# Singleton instance
conversation_summarizer = ConversationSummarizer()
