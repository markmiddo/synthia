"""Web search integration for Synthia using Tavily API."""

from typing import Optional

from tavily import TavilyClient

from synthia.config import load_config


class WebSearch:
    """Web search using Tavily API - optimized for AI/LLM use cases."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Tavily client.

        Args:
            api_key: Tavily API key. If not provided, loads from config.
        """
        if not api_key:
            config = load_config()
            api_key = config.get("tavily_api_key", "")

        if not api_key:
            raise ValueError("Tavily API key not configured. Add 'tavily_api_key' to config.yaml")

        self.client = TavilyClient(api_key=api_key)

    def search(self, query: str, max_results: int = 3) -> dict:
        """Search the web and return summarized results.

        Args:
            query: Search query
            max_results: Maximum number of results to return

        Returns:
            Dict with 'answer' (AI summary) and 'sources' (list of URLs)
        """
        try:
            # Use search_context for a concise answer
            response = self.client.search(
                query=query,
                search_depth="basic",
                max_results=max_results,
                include_answer=True,
            )

            answer = response.get("answer", "")
            sources = []

            for result in response.get("results", []):
                sources.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", "")[:200],
                })

            return {
                "answer": answer,
                "sources": sources,
                "success": True,
            }

        except Exception as e:
            print(f"Web search error: {e}")
            return {
                "answer": f"Search failed: {str(e)}",
                "sources": [],
                "success": False,
            }

    def quick_answer(self, query: str) -> str:
        """Get a quick answer for voice response.

        Args:
            query: The question to answer

        Returns:
            A concise answer string suitable for TTS
        """
        result = self.search(query, max_results=3)

        if result["success"] and result["answer"]:
            return result["answer"]
        elif result["sources"]:
            # Fallback to first snippet if no answer
            return result["sources"][0]["snippet"]
        else:
            return "I couldn't find an answer to that."


def web_search(query: str) -> str:
    """Convenience function for web search.

    Args:
        query: Search query

    Returns:
        Answer string for voice response
    """
    try:
        searcher = WebSearch()
        return searcher.quick_answer(query)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Search error: {e}"
