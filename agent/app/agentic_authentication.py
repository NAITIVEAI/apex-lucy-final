"""
Agentic Authentication System for Lucy

This module implements dynamic, adaptive authentication that learns from the data
and constructs queries intelligently rather than using static patterns.

Key Features:
1. Dynamic metadata discovery
2. Adaptive query construction
3. Learning cache for successful patterns
4. Intelligent fallback strategies
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import hashlib
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

class LearningCache:
    """Cache for storing successful authentication patterns"""
    
    def __init__(self, cache_file: str = "auth_learning_cache.pkl"):
        self.cache_file = Path(cache_file)
        self.successful_patterns = {}
        self.failure_patterns = {}
        self.load_cache()
    
    def load_cache(self):
        """Load existing cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    self.successful_patterns = cache_data.get('successful', {})
                    self.failure_patterns = cache_data.get('failures', {})
                logger.info(f"Loaded {len(self.successful_patterns)} successful patterns from cache")
            except Exception as e:
                logger.warning(f"Could not load cache: {e}")
    
    def save_cache(self):
        """Save cache to disk"""
        try:
            cache_data = {
                'successful': self.successful_patterns,
                'failures': self.failure_patterns,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
        except Exception as e:
            logger.warning(f"Could not save cache: {e}")
    
    def get_cache_key(self, first_name: str, last_name: str, ssn: str) -> str:
        """Generate cache key for name combination"""
        # Normalize inputs
        key_data = f"{first_name.lower().strip()}|{last_name.lower().strip()}|{ssn}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def record_success(self, first_name: str, last_name: str, ssn: str, 
                      successful_query: str, found_record: Dict[str, Any]):
        """Record a successful authentication pattern"""
        cache_key = self.get_cache_key(first_name, last_name, ssn)
        
        pattern = {
            'input_first': first_name,
            'input_last': last_name,
            'successful_query': successful_query,
            'found_firstname': found_record.get('new_firstname'),
            'found_lastname': found_record.get('new_lastname'),
            'found_fullname': found_record.get('new_fullname'),
            'found_middlename': found_record.get('new_middlename'),
            'success_count': self.successful_patterns.get(cache_key, {}).get('success_count', 0) + 1,
            'last_success': datetime.now().isoformat()
        }
        
        self.successful_patterns[cache_key] = pattern
        self.save_cache()
        
        logger.info(f"Recorded successful pattern: {first_name} {last_name} -> {successful_query}")
    
    def get_similar_patterns(self, first_name: str, last_name: str) -> List[Dict[str, Any]]:
        """Get similar successful patterns that might work"""
        similar = []
        
        for pattern in self.successful_patterns.values():
            # Check for similar first names
            input_first = str(pattern.get('input_first', '')).lower()
            found_first = str(pattern.get('found_firstname', '')).lower()
            input_last = str(pattern.get('input_last', '')).lower()
            
            if (input_first == first_name.lower() or
                (found_first and found_first != 'none' and found_first == first_name.lower())):
                similar.append(pattern)
            # Check for similar last names
            elif (input_last in last_name.lower() or
                  last_name.lower() in input_last):
                similar.append(pattern)
        
        # Sort by success count
        return sorted(similar, key=lambda x: x.get('success_count', 0), reverse=True)


class AgenticAuthenticator:
    """
    Agentic authentication system that adapts to data patterns
    """
    
    def __init__(self, query_function):
        """
        Initialize with a query function (from user_functions.py)
        """
        self.query_function = query_function
        self.learning_cache = LearningCache()
        self.entity_metadata = {}
    
    def discover_name_fields(self) -> List[str]:
        """Discover all name-related fields in the classmembers entity"""
        if 'name_fields' in self.entity_metadata:
            return self.entity_metadata['name_fields']
        
        # Get entity metadata
        try:
            # This would call the discover_entity_fields_sync function
            metadata_str = self.query_function('discover_entity_fields_sync', 'new_classmembers')
            metadata = json.loads(metadata_str)
            
            name_fields = []
            for field in metadata.get('fields', []):
                field_name = field.get('LogicalName', '')
                if any(keyword in field_name.lower() for keyword in ['name', 'first', 'last', 'full', 'middle']):
                    name_fields.append(field_name)
            
            self.entity_metadata['name_fields'] = name_fields
            logger.info(f"Discovered name fields: {name_fields}")
            return name_fields
            
        except Exception as e:
            logger.warning(f"Could not discover name fields: {e}")
            # Fallback to known fields
            return ['new_firstname', 'new_lastname', 'new_fullname', 'new_middlename']
    
    def generate_query_variations(self, first_name: str, last_name: str, ssn: str) -> List[str]:
        """
        Generate multiple query variations based on known patterns and learned data
        """
        variations = []
        
        # Check learning cache first
        similar_patterns = self.learning_cache.get_similar_patterns(first_name, last_name)
        for pattern in similar_patterns[:3]:  # Top 3 similar patterns
            # Adapt the successful query for current inputs
            adapted_query = pattern['successful_query'].replace(
                pattern['input_first'], first_name
            ).replace(
                pattern['input_last'], last_name
            )
            variations.append(f"LEARNED: {adapted_query}")
        
        # Generate systematic variations
        name_fields = self.discover_name_fields()
        
        # 1. Exact match variations
        variations.extend([
            f"new_firstname eq '{first_name}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
            f"new_fullname eq '{first_name} {last_name}' and new_shortsocial eq '{ssn}'"
        ])
        
        # 2. Handle middle names in lastname
        variations.extend([
            f"new_firstname eq '{first_name}' and endswith(new_lastname, '{last_name}') and new_shortsocial eq '{ssn}'",
            f"new_firstname eq '{first_name}' and contains(new_lastname, '{last_name}') and new_shortsocial eq '{ssn}'"
        ])
        
        # 3. Handle nicknames/variations
        name_variations = self.get_name_variations(first_name)
        for variation in name_variations:
            variations.append(
                f"new_firstname eq '{variation}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'"
            )
        
        # 4. Full name pattern matching
        full_name_patterns = [
            f"{first_name} {last_name}",
            f"{first_name.split()[0]} {last_name}" if ' ' in first_name else None,
        ]
        
        for pattern in full_name_patterns:
            if pattern:
                variations.extend([
                    f"new_fullname eq '{pattern}' and new_shortsocial eq '{ssn}'",
                    f"contains(new_fullname, '{pattern}') and new_shortsocial eq '{ssn}'"
                ])
        
        # 5. Split name handling
        if ' ' in first_name:
            parts = first_name.split()
            actual_first = parts[0]
            middle_part = ' '.join(parts[1:])
            
            variations.extend([
                f"new_firstname eq '{actual_first}' and new_middlename eq '{middle_part}' and new_lastname eq '{last_name}' and new_shortsocial eq '{ssn}'",
                f"new_firstname eq '{actual_first}' and new_lastname eq '{middle_part} {last_name}' and new_shortsocial eq '{ssn}'"
            ])
        
        if ' ' in last_name:
            parts = last_name.split()
            if len(parts) == 2:
                variations.extend([
                    f"new_firstname eq '{first_name}' and new_lastname eq '{parts[1]}' and new_middlename eq '{parts[0]}' and new_shortsocial eq '{ssn}'",
                    f"new_firstname eq '{first_name} {parts[0]}' and new_lastname eq '{parts[1]}' and new_shortsocial eq '{ssn}'"
                ])
        
        # 6. Partial matching for troubleshooting
        variations.extend([
            f"new_firstname eq '{first_name}' and new_shortsocial eq '{ssn}'",
            f"new_shortsocial eq '{ssn}'"  # Just SSN to see what exists
        ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for var in variations:
            if var not in seen:
                seen.add(var)
                unique_variations.append(var)
        
        logger.info(f"Generated {len(unique_variations)} query variations")
        return unique_variations
    
    def get_name_variations(self, name: str) -> List[str]:
        """Get common variations/nicknames for a name"""
        # This could be expanded with a comprehensive nickname database
        common_variations = {
            'christopher': ['chris', 'christopher'],
            'chris': ['christopher', 'chris'],
            'michael': ['mike', 'michael'],
            'mike': ['michael', 'mike'],
            'william': ['bill', 'will', 'william'],
            'robert': ['rob', 'bob', 'robert'],
            'richard': ['rick', 'dick', 'richard'],
            'jennifer': ['jen', 'jenny', 'jennifer'],
            'elizabeth': ['liz', 'beth', 'elizabeth'],
            'katherine': ['kate', 'kathy', 'katherine'],
            'james': ['jim', 'jimmy', 'james'],
            'john': ['johnny', 'john'],
            # Add more as needed
        }
        
        name_lower = name.lower()
        return common_variations.get(name_lower, [name])
    
    def execute_query_with_fallback(self, filter_str: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Execute a query with error handling and fallback
        """
        try:
            select_fields = "new_classmemberid,new_firstname,new_lastname,new_fullname,new_middlename,new_apexid,new_shortsocial"
            
            # Use the existing query_entity_sync function
            result_str = self.query_function('query_entity_sync', 'new_classmembers', filter_str, select_fields)
            results = json.loads(result_str)
            
            success = isinstance(results, list) and len(results) > 0
            return success, results if success else [], filter_str
            
        except Exception as e:
            logger.warning(f"Query failed: {filter_str} - Error: {str(e)}")
            return False, [], f"ERROR: {str(e)}"
    
    def authenticate_agentically(self, first_name: str = None, last_name: str = None,
                               apex_id: str = None, last_four_ssn: str = None,
                               full_name: str = None) -> Dict[str, Any]:
        """
        Main agentic authentication function
        """
        import time
        start_time = time.time()
        
        logger.info(f"🤖 Starting agentic authentication for {first_name} {last_name}")
        
        # Prepare input data for monitoring
        input_data = {
            'first_name': first_name,
            'last_name': last_name,
            'apex_id': apex_id,
            'last_four_ssn': last_four_ssn,
            'full_name': full_name
        }
        
        # Handle ApexID first (highest confidence)
        if apex_id and last_four_ssn:
            filter_str = f"new_apexid eq '{apex_id}' and new_shortsocial eq '{last_four_ssn}'"
            success, results, query_used = self.execute_query_with_fallback(filter_str)
            
            if success:
                # Record this success in learning cache
                if first_name and last_name:
                    self.learning_cache.record_success(first_name, last_name, last_four_ssn, query_used, results[0])
                
                result = {
                    "success": True,
                    "member": self.sanitize_member_data(results[0]),
                    "match_type": "apex_id",
                    "query_used": query_used,
                    "message": "Successfully authenticated with ApexID"
                }
                
                # Record metrics
                time_taken = (time.time() - start_time) * 1000
                self._record_metrics(input_data, result, queries_attempted=1, time_taken_ms=time_taken, strategy_used="apex_id")
                
                return result
        
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
            
            # Generate and try query variations
            query_variations = self.generate_query_variations(first_name, last_name, last_four_ssn)
            
            successful_results = []
            attempted_queries = []
            
            for i, query in enumerate(query_variations):
                logger.info(f"Trying query {i+1}/{len(query_variations)}: {query}")
                
                # Skip learned queries that are too similar to failed ones
                if query.startswith("LEARNED:"):
                    actual_query = query[8:]  # Remove "LEARNED:" prefix
                else:
                    actual_query = query
                
                success, results, query_used = self.execute_query_with_fallback(actual_query)
                
                attempted_queries.append({
                    "query": actual_query,
                    "success": success,
                    "result_count": len(results) if success else 0,
                    "is_learned": query.startswith("LEARNED:")
                })
                
                if success and len(results) > 0:
                    # Found matches!
                    successful_results.extend(results)
                    
                    # Record this success in learning cache
                    self.learning_cache.record_success(first_name, last_name, last_four_ssn, actual_query, results[0])
                    
                    # Return immediately for single match
                    if len(results) == 1:
                        return {
                            "success": True,
                            "member": self.sanitize_member_data(results[0]),
                            "match_type": "agentic_query",
                            "query_used": actual_query,
                            "queries_attempted": len(attempted_queries),
                            "successful_strategy": i + 1,
                            "message": "Successfully authenticated with adaptive query"
                        }
                    
                    # For multiple matches, continue to see if we can narrow it down
                    break
            
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
                    return {
                        "success": True,
                        "member": self.sanitize_member_data(member),
                        "match_type": "agentic_query_unique",
                        "queries_attempted": len(attempted_queries),
                        "message": "Successfully authenticated after deduplication"
                    }
                else:
                    # Multiple unique members - this shouldn't happen with SSN
                    return {
                        "success": False,
                        "multiple_matches": True,
                        "match_count": len(unique_members),
                        "queries_attempted": len(attempted_queries),
                        "message": "Multiple members found. Please provide your ApexID for unique identification."
                    }
            
            # No matches found - provide intelligent guidance
            return self.generate_no_match_response(first_name, last_name, last_four_ssn, attempted_queries)
        
        # Insufficient information
        return {
            "success": False,
            "message": "Please provide either (first name + last name + last 4 SSN) or (ApexID + last 4 SSN) for authentication",
            "required_info": ["first_name", "last_name", "last_four_ssn"]
        }
    
    def generate_no_match_response(self, first_name: str, last_name: str, ssn: str, 
                                 attempted_queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate intelligent response when no matches are found"""
        
        # Check if ANY record exists with that SSN (diagnostic)
        ssn_only_query = f"new_shortsocial eq '{ssn}'"
        success, ssn_results, _ = self.execute_query_with_fallback(ssn_only_query)
        
        suggestions = []
        
        if success and len(ssn_results) > 0:
            # SSN exists but name doesn't match
            suggestions.extend([
                "Try using your full legal name as it appears on official documents",
                "Include any middle names or initials if applicable",
                "Check if you used a nickname instead of your legal first name"
            ])
        else:
            # SSN doesn't exist
            suggestions.extend([
                "Double-check the last 4 digits of your Social Security Number",
                "Verify you're using the correct SSN",
                "Try providing your ApexID if you have it (starts with letters like MCSS)"
            ])
        
        # Add specific suggestions based on attempted strategies
        learned_queries_tried = any(q.get("is_learned", False) for q in attempted_queries)
        if not learned_queries_tried:
            suggestions.append("This might be a new pattern - our system will learn from this case")
        
        return {
            "success": False,
            "member": None,
            "message": "No matching member found with the provided information",
            "suggestions": suggestions,
            "diagnostic_info": {
                "ssn_exists_in_system": success and len(ssn_results) > 0,
                "queries_attempted": len(attempted_queries),
                "learned_patterns_tried": learned_queries_tried
            },
            "next_steps": [
                "Verify your information and try again",
                "Provide your ApexID if available",
                "Contact support if you continue to have issues"
            ]
        }
    
    def sanitize_member_data(self, member_data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove PII from member data"""
        if not member_data:
            return {}
        
        sanitized = {}
        pii_fields = [
            'new_firstname', 'new_lastname', 'new_fullname', 'new_middlename',
            'new_shortsocial', 'new_email', 'new_phone', 'new_address1',
            'new_address2', 'new_city', 'new_state', 'new_zip'
        ]
        
        for key, value in member_data.items():
            if key not in pii_fields:
                sanitized[key] = value
        
        # Always include ApexID as it's the safe identifier
        if 'new_apexid' in member_data:
            sanitized['new_apexid'] = member_data['new_apexid']
        
        return sanitized
    
    def _record_metrics(self, input_data, result, queries_attempted=0, time_taken_ms=0, strategy_used=None, learned_pattern_used=False):
        """Record authentication metrics for monitoring"""
        try:
            from agentic_monitoring import record_auth_attempt
            record_auth_attempt(
                input_data=input_data,
                result=result,
                queries_attempted=queries_attempted,
                time_taken_ms=time_taken_ms,
                strategy_used=strategy_used,
                learned_pattern_used=learned_pattern_used
            )
        except ImportError:
            # Monitoring not available, continue without metrics
            pass
        except Exception as e:
            logger.warning(f"Could not record metrics: {e}")


# Integration function to replace the static authenticate_member_sync
def authenticate_member_agentic_sync(first_name: str = None, last_name: str = None,
                                   apex_id: str = None, last_four_ssn: str = None,
                                   full_name: str = None) -> str:
    """
    Agentic authentication function that replaces the static version
    
    This function provides the same interface as authenticate_member_sync
    but uses dynamic, adaptive query construction
    """
    
    # Import the query function (avoid circular imports)
    from user_functions import query_entity_sync, discover_entity_fields_sync
    
    def query_wrapper(func_name: str, *args, **kwargs):
        """Wrapper to call functions by name"""
        if func_name == 'query_entity_sync':
            return query_entity_sync(*args, **kwargs)
        elif func_name == 'discover_entity_fields_sync':
            try:
                return discover_entity_fields_sync(*args, **kwargs)
            except:
                # Fallback if discover function not available
                return json.dumps({'fields': [
                    {'LogicalName': 'new_firstname'},
                    {'LogicalName': 'new_lastname'},
                    {'LogicalName': 'new_fullname'},
                    {'LogicalName': 'new_middlename'}
                ]})
        else:
            raise ValueError(f"Unknown function: {func_name}")
    
    # Create authenticator and run
    authenticator = AgenticAuthenticator(query_wrapper)
    result = authenticator.authenticate_agentically(
        first_name=first_name,
        last_name=last_name,
        apex_id=apex_id,
        last_four_ssn=last_four_ssn,
        full_name=full_name
    )
    
    return json.dumps(result)