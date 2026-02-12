"""
Monitoring and metrics for Lucy's agentic authentication system

This module tracks authentication patterns, success rates, and learning effectiveness
to ensure the agentic approach is performing optimally.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict, Counter
import statistics

logger = logging.getLogger(__name__)

class AgenticAuthMonitor:
    """Monitor and analyze agentic authentication performance"""
    
    def __init__(self, metrics_file: str = "auth_metrics.jsonl"):
        self.metrics_file = metrics_file
        self.session_metrics = []
    
    def record_authentication_attempt(self, 
                                    input_data: Dict[str, Any],
                                    result: Dict[str, Any],
                                    queries_attempted: int = 0,
                                    time_taken_ms: float = 0,
                                    strategy_used: str = None,
                                    learned_pattern_used: bool = False):
        """Record an authentication attempt for analysis"""
        
        metric = {
            'timestamp': datetime.now().isoformat(),
            'input': {
                'has_first_name': bool(input_data.get('first_name')),
                'has_last_name': bool(input_data.get('last_name')),
                'has_apex_id': bool(input_data.get('apex_id')),
                'has_ssn': bool(input_data.get('last_four_ssn')),
                'has_full_name': bool(input_data.get('full_name'))
            },
            'result': {
                'success': result.get('success', False),
                'match_type': result.get('match_type'),
                'member_found': bool(result.get('member'))
            },
            'performance': {
                'queries_attempted': queries_attempted,
                'time_taken_ms': time_taken_ms,
                'strategy_used': strategy_used,
                'learned_pattern_used': learned_pattern_used
            }
        }
        
        # Add to session metrics
        self.session_metrics.append(metric)
        
        # Append to persistent log
        try:
            with open(self.metrics_file, 'a') as f:
                f.write(json.dumps(metric) + '\n')
        except Exception as e:
            logger.warning(f"Could not write metrics: {e}")
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session metrics"""
        if not self.session_metrics:
            return {"message": "No authentication attempts in current session"}
        
        total_attempts = len(self.session_metrics)
        successful_attempts = sum(1 for m in self.session_metrics if m['result']['success'])
        
        queries_per_attempt = [m['performance']['queries_attempted'] for m in self.session_metrics if m['performance']['queries_attempted'] > 0]
        learned_pattern_uses = sum(1 for m in self.session_metrics if m['performance']['learned_pattern_used'])
        
        return {
            'session_summary': {
                'total_attempts': total_attempts,
                'successful_attempts': successful_attempts,
                'success_rate': round((successful_attempts / total_attempts) * 100, 2),
                'avg_queries_per_attempt': round(statistics.mean(queries_per_attempt), 2) if queries_per_attempt else 0,
                'learned_pattern_usage': round((learned_pattern_uses / total_attempts) * 100, 2),
                'session_duration': self._get_session_duration()
            },
            'strategy_breakdown': self._get_strategy_breakdown(),
            'performance_trends': self._get_performance_trends()
        }
    
    def get_historical_analysis(self, days: int = 7) -> Dict[str, Any]:
        """Analyze historical authentication patterns"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            historical_metrics = []
            
            if os.path.exists(self.metrics_file):
                with open(self.metrics_file, 'r') as f:
                    for line in f:
                        try:
                            metric = json.loads(line.strip())
                            metric_date = datetime.fromisoformat(metric['timestamp'])
                            if metric_date >= cutoff_date:
                                historical_metrics.append(metric)
                        except Exception:
                            continue
            
            if not historical_metrics:
                return {"message": f"No authentication data found for last {days} days"}
            
            return self._analyze_metrics(historical_metrics, f"Last {days} days")
            
        except Exception as e:
            logger.error(f"Error analyzing historical data: {e}")
            return {"error": str(e)}
    
    def _analyze_metrics(self, metrics: List[Dict], period: str) -> Dict[str, Any]:
        """Analyze a set of metrics"""
        total = len(metrics)
        successful = sum(1 for m in metrics if m['result']['success'])
        
        # Query efficiency analysis
        queries_data = [m['performance']['queries_attempted'] for m in metrics if m['performance']['queries_attempted'] > 0]
        
        # Learning pattern analysis
        learned_uses = sum(1 for m in metrics if m['performance']['learned_pattern_used'])
        
        # Strategy effectiveness
        strategy_success = defaultdict(list)
        for m in metrics:
            strategy = m['performance']['strategy_used']
            if strategy:
                strategy_success[strategy].append(m['result']['success'])
        
        strategy_stats = {}
        for strategy, successes in strategy_success.items():
            strategy_stats[strategy] = {
                'attempts': len(successes),
                'success_rate': round((sum(successes) / len(successes)) * 100, 2)
            }
        
        return {
            'period': period,
            'overall_stats': {
                'total_attempts': total,
                'success_rate': round((successful / total) * 100, 2),
                'avg_queries_per_attempt': round(statistics.mean(queries_data), 2) if queries_data else 0,
                'median_queries': statistics.median(queries_data) if queries_data else 0,
                'learning_cache_usage': round((learned_uses / total) * 100, 2)
            },
            'strategy_effectiveness': strategy_stats,
            'efficiency_trends': {
                'min_queries': min(queries_data) if queries_data else 0,
                'max_queries': max(queries_data) if queries_data else 0,
                'most_common_query_count': Counter(queries_data).most_common(1)[0] if queries_data else None
            }
        }
    
    def _get_session_duration(self) -> str:
        """Calculate session duration"""
        if len(self.session_metrics) < 2:
            return "< 1 minute"
        
        first = datetime.fromisoformat(self.session_metrics[0]['timestamp'])
        last = datetime.fromisoformat(self.session_metrics[-1]['timestamp'])
        duration = last - first
        
        minutes = duration.total_seconds() / 60
        if minutes < 1:
            return f"{int(duration.total_seconds())} seconds"
        elif minutes < 60:
            return f"{int(minutes)} minutes"
        else:
            hours = minutes / 60
            return f"{hours:.1f} hours"
    
    def _get_strategy_breakdown(self) -> Dict[str, int]:
        """Get breakdown of strategies used"""
        strategies = [m['performance']['strategy_used'] for m in self.session_metrics if m['performance']['strategy_used']]
        return dict(Counter(strategies))
    
    def _get_performance_trends(self) -> Dict[str, Any]:
        """Analyze performance trends in session"""
        if len(self.session_metrics) < 2:
            return {"message": "Insufficient data for trend analysis"}
        
        # Query count trend
        queries_over_time = [m['performance']['queries_attempted'] for m in self.session_metrics if m['performance']['queries_attempted'] > 0]
        
        # Success rate trend (looking at last 5 vs first 5)
        recent_success = sum(1 for m in self.session_metrics[-5:] if m['result']['success'])
        early_success = sum(1 for m in self.session_metrics[:5] if m['result']['success'])
        
        return {
            'query_efficiency_improving': len(queries_over_time) > 1 and queries_over_time[-1] <= queries_over_time[0],
            'recent_success_rate': round((recent_success / min(5, len(self.session_metrics))) * 100, 2),
            'early_success_rate': round((early_success / min(5, len(self.session_metrics))) * 100, 2),
            'learning_pattern_adoption': sum(1 for m in self.session_metrics[-5:] if m['performance']['learned_pattern_used'])
        }
    
    def generate_recommendations(self) -> List[str]:
        """Generate recommendations based on current metrics"""
        recommendations = []
        
        if not self.session_metrics:
            return ["No authentication attempts recorded yet"]
        
        summary = self.get_session_summary()
        stats = summary.get('session_summary', {})
        
        # Success rate recommendations
        success_rate = stats.get('success_rate', 0)
        if success_rate < 80:
            recommendations.append(f"Success rate is {success_rate}% - consider expanding query variations")
        elif success_rate > 95:
            recommendations.append(f"Excellent success rate of {success_rate}% - system performing optimally")
        
        # Query efficiency recommendations
        avg_queries = stats.get('avg_queries_per_attempt', 0)
        if avg_queries > 5:
            recommendations.append(f"Average {avg_queries} queries per attempt - learning cache may need tuning")
        elif avg_queries < 2:
            recommendations.append(f"Very efficient with {avg_queries} avg queries - learning cache working well")
        
        # Learning pattern recommendations
        cache_usage = stats.get('learned_pattern_usage', 0)
        if cache_usage < 20:
            recommendations.append(f"Learning cache usage is {cache_usage}% - consider extending cache retention")
        elif cache_usage > 50:
            recommendations.append(f"High cache usage of {cache_usage}% - learning system is effective")
        
        return recommendations


# Global monitor instance
_monitor = AgenticAuthMonitor()

def record_auth_attempt(input_data: Dict[str, Any], result: Dict[str, Any], **kwargs):
    """Convenience function to record authentication attempts"""
    _monitor.record_authentication_attempt(input_data, result, **kwargs)

def get_monitoring_summary() -> Dict[str, Any]:
    """Get current monitoring summary"""
    try:
        return _monitor.get_session_summary()
    except Exception as e:
        logger.error(f"Error getting monitoring summary: {e}")
        return {
            "session_summary": {
                "total_attempts": 0,
                "successful_attempts": 0,
                "success_rate": 0,
                "avg_queries_per_attempt": 0,
                "learned_pattern_usage": 0,
                "session_duration": "No data"
            },
            "strategy_breakdown": {},
            "performance_trends": {"message": "No data available"}
        }

def get_historical_analysis(days: int = 7) -> Dict[str, Any]:
    """Get historical analysis"""
    try:
        return _monitor.get_historical_analysis(days)
    except Exception as e:
        logger.error(f"Error getting historical analysis: {e}")
        return {"message": f"No historical data available for last {days} days"}

def get_recommendations() -> List[str]:
    """Get performance recommendations"""
    try:
        return _monitor.generate_recommendations()
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return ["System monitoring starting up - check back later for recommendations"]

def monitoring_report_sync() -> str:
    """Sync function to get monitoring report for Lucy"""
    try:
        summary = get_monitoring_summary()
        historical = get_historical_analysis(7)
        recommendations = get_recommendations()
        
        report = {
            "current_session": summary,
            "historical_analysis": historical,
            "recommendations": recommendations,
            "report_generated": datetime.now().isoformat()
        }
        
        return json.dumps(report, indent=2)
        
    except Exception as e:
        logger.error(f"Error generating monitoring report: {e}")
        return json.dumps({"error": str(e)})