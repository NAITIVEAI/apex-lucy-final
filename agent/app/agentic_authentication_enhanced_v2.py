"""
Enhanced Agentic Authentication System v2 - Better Middle Initial Handling

This version specifically addresses the issue where users provide middle initials
but the system can't find matches due to incomplete name variation generation.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import hashlib
import pickle
from pathlib import Path
from agentic_authentication import AgenticAuthenticator, LearningCache

logger = logging.getLogger(__name__)


class EnhancedAgenticAuthenticatorV2(AgenticAuthenticator):
    """
    Enhanced authentication with better middle initial and name variation handling
    """
    
    def generate_comprehensive_query_variations(
        self,
        first_name: str,
        last_name: str,
        ssn: str,
        full_name: str | None = None,
    ) -> List[str]:
        """
        Generate comprehensive query variations with better middle initial handling
        """
        variations = []
        
        # Check learning cache first
        similar_patterns = self.learning_cache.get_similar_patterns(first_name, last_name)
        for pattern in similar_patterns[:3]:
            adapted_query = pattern['successful_query'].replace(
                pattern['input_first'], first_name
            ).replace(
                pattern['input_last'], last_name
            )
            variations.append(f"LEARNED: {adapted_query}")
        
        # 1. Exact match variations
        variations.extend([
            f"new_firstname eq '{first_name}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
            f"new_fullname eq '{first_name} {last_name}' and new_shortsocial eq '{ssn}'"
        ])

        if full_name:
            cleaned_full = " ".join(full_name.strip().split())
            if cleaned_full:
                variations.append(
                    f"new_fullname eq '{cleaned_full}' and new_shortsocial eq '{ssn}'"
                )
        
        # 2. Handle middle initials/names in the provided name
        if ' ' in first_name:
            # User provided "Amina J" or "Lilia G" as first name
            parts = first_name.split()
            actual_first = parts[0]
            middle_parts = ' '.join(parts[1:])
            
            # Try various combinations
            variations.extend([
                # CRITICAL: Sometimes middle initial is stored in first name field (like "Lilia G")
                f"new_firstname eq '{first_name}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                # Middle initial in middle name field
                f"new_firstname eq '{actual_first}' and new_middlename eq '{middle_parts}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                # Middle initial in last name field 
                f"new_firstname eq '{actual_first}' and new_lastname eq '{middle_parts} {last_name}' and new_shortsocial eq '{ssn}'",
                # Full name with all parts
                f"new_fullname eq '{first_name} {last_name}' and new_shortsocial eq '{ssn}'",
                f"contains(new_fullname, '{actual_first}') and contains(new_fullname, '{middle_parts}') and contains(new_fullname, '{last_name}') and new_shortsocial eq '{ssn}'",
                # Just first name + last name, ignoring middle
                f"new_firstname eq '{actual_first}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                f"new_fullname eq '{actual_first} {last_name}' and new_shortsocial eq '{ssn}'",
                # Try with full first name in full name field
                f"contains(new_fullname, '{first_name} {last_name}') and new_shortsocial eq '{ssn}'"
            ])
        
        if ' ' in last_name:
            # User provided "Hughes Smith" as last name
            parts = last_name.split()
            
            # Try treating different parts as middle names
            for i in range(len(parts)):
                if i == 0:
                    # First part might be middle name
                    potential_middle = parts[0]
                    potential_last = ' '.join(parts[1:])
                    variations.extend([
                        f"new_firstname eq '{first_name}' and new_middlename eq '{potential_middle}' and new_lastname eq '{potential_last}' and new_shortsocial eq '{ssn}'",
                        f"new_firstname eq '{first_name} {potential_middle}' and new_lastname eq '{potential_last}' and new_shortsocial eq '{ssn}'"
                    ])
                else:
                    # Later parts might be middle names
                    potential_last = parts[i]
                    potential_middle = ' '.join(parts[:i])
                    variations.extend([
                        f"new_firstname eq '{first_name}' and new_middlename eq '{potential_middle}' and new_lastname eq '{potential_last}' and new_shortsocial eq '{ssn}'",
                        f"new_firstname eq '{first_name} {potential_middle}' and new_lastname eq '{potential_last}' and new_shortsocial eq '{ssn}'"
                    ])
        
        # 3. Generate middle initial variations even when not provided
        # Common middle initials to try
        common_initials = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
        
        # Only try this if we haven't found matches with previous variations
        for initial in common_initials[:5]:  # Try first 5 most common
            variations.extend([
                f"new_firstname eq '{first_name}' and new_middlename eq '{initial}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                f"new_fullname eq '{first_name} {initial} {last_name}' and new_shortsocial eq '{ssn}'",
                f"contains(new_fullname, '{first_name} {initial} {last_name}') and new_shortsocial eq '{ssn}'"
            ])
        
        # 4. Flexible full name matching
        full_name_patterns = [
            f"{first_name} {last_name}",
            f"{first_name.split()[0]} {last_name}" if ' ' in first_name else None,
        ]
        
        for pattern in full_name_patterns:
            if pattern:
                variations.extend([
                    f"new_fullname eq '{pattern}' and new_shortsocial eq '{ssn}'",
                    f"contains(new_fullname, '{pattern}') and new_shortsocial eq '{ssn}'",
                    # Try startswith + endswith for middle initial pattern (e.g., "Amina * Hughes")
                    f"startswith(new_fullname, '{pattern.split()[0]}') and endswith(new_fullname, '{pattern.split()[-1]}') and new_shortsocial eq '{ssn}'" if len(pattern.split()) >= 2 else None
                ])
        
        # 5. Handle endswith and contains for flexibility
        variations.extend([
            f"new_firstname eq '{first_name}' and endswith(new_lastname, '{last_name}') and new_shortsocial eq '{ssn}'",
            f"new_firstname eq '{first_name}' and contains(new_lastname, '{last_name}') and new_shortsocial eq '{ssn}'",
            f"contains(new_fullname, '{first_name}') and contains(new_fullname, '{last_name}') and new_shortsocial eq '{ssn}'"
        ])
        
        # 6. Try common patterns where firstname includes middle initial
        # For cases like firstname="Amina D" lastname="Hughes"
        for initial in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M']:
            variations.append(
                f"new_firstname eq '{first_name} {initial}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'"
            )
        
        # 7. Nickname variations
        name_variations = self.get_name_variations(first_name)
        for variation in name_variations:
            if variation != first_name:
                variations.extend([
                    f"new_firstname eq '{variation}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                    f"new_fullname eq '{variation} {last_name}' and new_shortsocial eq '{ssn}'",
                    f"contains(new_fullname, '{variation}') and contains(new_fullname, '{last_name}') and new_shortsocial eq '{ssn}'"
                ])
        
        # 7. Fallback patterns for troubleshooting
        variations.extend([
            f"new_firstname eq '{first_name}' and new_shortsocial eq '{ssn}'",
            f"contains(new_lastname, '{last_name}') and new_shortsocial eq '{ssn}'",
            f"new_shortsocial eq '{ssn}'"  # Just SSN to see what exists
        ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for var in variations:
            if var and var not in seen:
                seen.add(var)
                unique_variations.append(var)
        
        logger.info(f"Generated {len(unique_variations)} comprehensive query variations")
        return unique_variations
    
    def authenticate_agentically_v2(self, first_name: str = None, last_name: str = None,
                                   apex_id: str = None, last_four_ssn: str = None,
                                   full_name: str = None) -> Dict[str, Any]:
        """
        Enhanced agentic authentication with better name handling
        """
        import time
        start_time = time.time()
        
        logger.info(f"🤖 Starting enhanced v2 agentic authentication for {first_name} {last_name}")
        
        # Handle ApexID first (highest confidence)
        if apex_id and last_four_ssn:
            filter_str = f"new_apexid eq '{apex_id}' and new_shortsocial eq '{last_four_ssn}'"
            success, results, query_used = self.execute_query_with_fallback(filter_str)
            
            if success:
                if first_name and last_name:
                    self.learning_cache.record_success(first_name, last_name, last_four_ssn, query_used, results[0])
                
                return {
                    "success": True,
                    "member": self.sanitize_member_data(results[0]),
                    "match_type": "apex_id",
                    "query_used": query_used,
                    "message": "Successfully authenticated with ApexID"
                }
        
        # Handle name-based authentication
        if (first_name or full_name) and last_four_ssn:
            # Parse full name if provided
            if full_name and not (first_name and last_name):
                name_parts = full_name.strip().split()
                if len(name_parts) >= 2:
                    first_name = name_parts[0]
                    last_name = ' '.join(name_parts[1:])
                elif len(name_parts) == 1:
                    first_name = name_parts[0]
            
            if not (first_name and last_name):
                return {
                    "success": False,
                    "message": "Please provide both first and last name for authentication"
                }
            
            # Generate comprehensive query variations
            query_variations = self.generate_comprehensive_query_variations(
                first_name,
                last_name,
                last_four_ssn,
                full_name=full_name,
            )
            
            successful_results = []
            attempted_queries = []
            first_success_query = None
            
            def _is_ssn_only(query: str) -> bool:
                return query.strip() == f"new_shortsocial eq '{last_four_ssn}'"

            for i, query in enumerate(query_variations):
                logger.info(f"Trying query {i+1}/{len(query_variations)}: {query}")
                
                if query.startswith("LEARNED:"):
                    actual_query = query[8:]
                else:
                    actual_query = query
                
                if successful_results and _is_ssn_only(actual_query):
                    logger.info("Skipping SSN-only fallback because we already have matches")
                    attempted_queries.append({
                        "query": actual_query,
                        "success": False,
                        "result_count": 0,
                        "is_learned": query.startswith("LEARNED:"),
                    })
                    continue

                success, results, query_used = self.execute_query_with_fallback(actual_query)
                
                attempted_queries.append({
                    "query": actual_query,
                    "success": success,
                    "result_count": len(results) if success else 0,
                    "is_learned": query.startswith("LEARNED:")
                })
                
                if success and len(results) > 0:
                    successful_results.extend(results)
                    if first_success_query is None:
                        first_success_query = actual_query

                    # Return immediately for single match
                    if len(results) == 1:
                        self.learning_cache.record_success(
                            first_name, last_name, last_four_ssn, actual_query, results[0]
                        )
                        return {
                            "success": True,
                            "member": self.sanitize_member_data(results[0]),
                            "match_type": "enhanced_v2_query",
                            "query_used": actual_query,
                            "queries_attempted": len(attempted_queries),
                            "successful_strategy": i + 1,
                            "message": "Successfully authenticated with enhanced name matching"
                        }
                    
                    # For multiple matches, continue to see if we can narrow it down
                    continue
            
            # Handle results
            if successful_results:
                # Deduplicate by member ID
                unique_members = {}
                for member in successful_results:
                    member_id = member.get('new_classmemberid')
                    if member_id and member_id not in unique_members:
                        unique_members[member_id] = member
                
                if len(unique_members) == 1:
                    member = list(unique_members.values())[0]
                    if first_success_query:
                        self.learning_cache.record_success(
                            first_name, last_name, last_four_ssn, first_success_query, member
                        )
                    return {
                        "success": True,
                        "member": self.sanitize_member_data(member),
                        "match_type": "enhanced_v2_unique",
                        "queries_attempted": len(attempted_queries),
                        "message": "Successfully authenticated after enhanced matching and deduplication"
                    }
                else:
                    # Multiple unique members found. Attempt automatic duplicate resolution.
                    candidates = list(unique_members.values())
                    resolution = self._resolve_duplicate_members(candidates, last_four_ssn)
                    if resolution.get("resolved_member"):
                        member = resolution["resolved_member"]
                        logger.info(
                            "Duplicate resolution applied: %s (confidence=%s reason=%s)",
                            resolution.get("strategy"),
                            resolution.get("confidence"),
                            resolution.get("reason"),
                        )
                        return {
                            "success": True,
                            "member": self.sanitize_member_data(member),
                            "match_type": "enhanced_v2_duplicate_auto",
                            "queries_attempted": len(attempted_queries),
                            "message": "Successfully authenticated after duplicate resolution"
                        }

                    if resolution.get("needs_address"):
                        return {
                            "success": False,
                            "message": (
                                "To make sure I pull the correct record, can you confirm your mailing address? "
                                "If you happen to have your ApexID, please include it with the last 4 digits of "
                                "your SSN."
                            ),
                            "needs_address": True,
                            "queries_attempted": len(attempted_queries)
                        }

                    # If duplicate resolution didn't apply, fall back to name guidance.
                    return {
                        "success": False,
                        "message": (
                            "I wasn't able to verify your record yet. Please provide your full legal name exactly "
                            "as it appears on official documents (including any middle names/initials or suffixes), "
                            "or your ApexID plus the last 4 digits of your SSN."
                        ),
                        "enhanced_matching": True,
                        "queries_attempted": len(attempted_queries)
                    }
            
            # No matches found with enhanced matching - be more secure
            # Check if ANY record exists with that SSN (diagnostic)
            ssn_only_filter = f"new_shortsocial eq '{last_four_ssn}'"
            success, ssn_results, _ = self.execute_query_with_fallback(ssn_only_filter)
            
            if success and len(ssn_results) > 0:
                # SSN exists but name doesn't match - DON'T reveal this fact
                return {
                    "success": False,
                    "message": (
                        "I wasn't able to find your record with the provided information. Please verify your full "
                        "legal name and try again, or provide your ApexID plus the last 4 digits of your SSN."
                    ),
                    "suggestions": [
                        "Double-check the spelling of your name",
                        "Try using your full legal name as it appears on official documents",
                        "Include any middle names or initials",
                        "Verify the last 4 digits of your SSN"
                    ],
                    "enhanced_matching_attempted": True,
                    "queries_attempted": len(attempted_queries)
                }
            else:
                # SSN doesn't exist
                return {
                    "success": False,
                    "message": (
                        "I wasn't able to find your record. Please verify the last 4 digits of your Social Security "
                        "Number and try again."
                    ),
                    "suggestions": [
                        "Double-check the last 4 digits of your SSN",
                        "If you have your ApexID (starts with letters), include it with the last 4 digits of your SSN"
                    ]
                }
        
        # Insufficient information
        return {
            "success": False,
            "message": "Please provide either (first name + last name + last 4 SSN) or (ApexID + last 4 SSN) for authentication",
            "required_info": ["first_name", "last_name", "last_four_ssn"]
        }

    @staticmethod
    def _normalize_value(value: str) -> str:
        if not value:
            return ""
        return " ".join(str(value).strip().lower().split())

    def _normalize_full_name(self, member: Dict[str, Any]) -> str:
        full = self._normalize_value(member.get("new_fullname", ""))
        if full:
            return full
        first = self._normalize_value(member.get("new_firstname", ""))
        last = self._normalize_value(member.get("new_lastname", ""))
        return " ".join([p for p in [first, last] if p]).strip()

    def _normalize_address(self, member: Dict[str, Any]) -> str:
        address = self._normalize_value(member.get("new_address", ""))
        city = self._normalize_value(member.get("new_city", ""))
        state = self._normalize_value(member.get("new_state", "")).upper()
        zip_code = self._normalize_value(member.get("new_zip", ""))
        parts = [address, city, state, zip_code]
        return "|".join([p for p in parts if p])

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1]
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _score_completeness(self, member: Dict[str, Any]) -> int:
        fields = [
            "new_fullname",
            "new_firstname",
            "new_lastname",
            "new_address",
            "new_city",
            "new_state",
            "new_zip",
        ]
        return sum(1 for field in fields if member.get(field))

    def _choose_best_record(self, members: List[Dict[str, Any]]) -> Dict[str, Any]:
        scored = []
        for member in members:
            modified = self._parse_dt(member.get("modifiedon"))
            created = self._parse_dt(member.get("createdon"))
            timestamp = modified or created
            completeness = self._score_completeness(member)
            apex_id = self._normalize_value(member.get("new_apexid", ""))
            scored.append((timestamp, completeness, apex_id, member))

        scored.sort(key=lambda item: (
            item[0] is not None,
            item[0] or datetime.min,
            item[1],
            item[2],
        ), reverse=True)
        return scored[0][3]

    def _resolve_duplicate_members(
        self,
        members: List[Dict[str, Any]],
        last_four_ssn: str,
    ) -> Dict[str, Any]:
        normalized_names = [self._normalize_full_name(m) for m in members]
        normalized_addresses = [self._normalize_address(m) for m in members]
        name_set = set([n for n in normalized_names if n])
        address_set = set([a for a in normalized_addresses if a])

        # All matches should already have same last-4, but we confirm for logging.
        duplicate_probability = 0.0
        reason = "ambiguous"
        strategy = None

        same_name = len(name_set) == 1 and bool(name_set)
        addresses_present = all(normalized_addresses)
        same_address = len(address_set) == 1 and addresses_present
        any_address_present = bool(address_set)

        if same_name and same_address:
            duplicate_probability = 0.98
            reason = "same_name_same_address"
            strategy = "auto_duplicate_same_address"
            selected = self._choose_best_record(members)
            logger.info(
                "Duplicate probability cloud: %s (reason=%s)",
                duplicate_probability,
                reason,
            )
            return {
                "resolved_member": selected,
                "confidence": duplicate_probability,
                "reason": reason,
                "strategy": strategy,
            }

        if same_name and any_address_present and len(address_set) == 1 and not addresses_present:
            duplicate_probability = 0.9
            reason = "same_name_address_missing"
            strategy = "auto_duplicate_address_missing"
            # Prefer records with addresses.
            with_address = [m for m in members if self._normalize_address(m)]
            selected = self._choose_best_record(with_address) if with_address else self._choose_best_record(members)
            logger.info(
                "Duplicate probability cloud: %s (reason=%s)",
                duplicate_probability,
                reason,
            )
            return {
                "resolved_member": selected,
                "confidence": duplicate_probability,
                "reason": reason,
                "strategy": strategy,
            }

        if same_name:
            duplicate_probability = 0.35
            reason = "same_name_address_differs"

        logger.info(
            "Duplicate probability cloud: %s (reason=%s)",
            duplicate_probability,
            reason,
        )
        return {
            "needs_address": True,
            "confidence": duplicate_probability,
            "reason": reason,
            "strategy": "request_address",
        }


def authenticate_member_enhanced_v2_sync(first_name: str = None, last_name: str = None,
                                        apex_id: str = None, last_four_ssn: str = None,
                                        full_name: str = None) -> str:
    """
    Enhanced v2 authentication function with comprehensive name variation handling
    """
    from user_functions import query_entity_sync, discover_entity_fields_sync
    
    def query_wrapper(func_name: str, *args, **kwargs):
        if func_name == 'query_entity_sync':
            return query_entity_sync(*args, **kwargs)
        elif func_name == 'discover_entity_fields_sync':
            try:
                return discover_entity_fields_sync(*args, **kwargs)
            except:
                return json.dumps({'fields': [
                    {'LogicalName': 'new_firstname'},
                    {'LogicalName': 'new_lastname'},
                    {'LogicalName': 'new_fullname'},
                    {'LogicalName': 'new_middlename'}
                ]})
        else:
            raise ValueError(f"Unknown function: {func_name}")
    
    # Create enhanced v2 authenticator
    authenticator = EnhancedAgenticAuthenticatorV2(query_wrapper)
    result = authenticator.authenticate_agentically_v2(
        first_name=first_name,
        last_name=last_name,
        apex_id=apex_id,
        last_four_ssn=last_four_ssn,
        full_name=full_name
    )
    
    return json.dumps(result)
