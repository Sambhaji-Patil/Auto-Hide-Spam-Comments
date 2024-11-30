import joblib
import requests
import os
import json
import hashlib
import sys

GITHUB_API_URL = "https://api.github.com/graphql"
CURSOR_CACHE_KEY = "spam-detection-cursor"

def save_cursor_to_cache(owner, repo, comment_type, cursor):
    """Save cursor data to GitHub Actions cache."""
    try:
        # Prepare cursor data
        cursor_data = {
            'owner': owner,
            'repo': repo,
            'comment_type': comment_type,
            'cursor': cursor
        }
        
        # Convert to JSON string
        cursor_json = json.dumps(cursor_data)
        
        # Write to a temporary file
        with open('/tmp/cursor_cache.json', 'w') as f:
            f.write(cursor_json)
        
        print(f"Cursor prepared for caching: {cursor_data}")
        return True
    except Exception as e:
        print(f"Error preparing cursor for cache: {e}")
        return False

def fetch_comments(owner, repo, headers, after_cursor=None, comment_type="discussion"):
    """
    Fetch comments with corrected parameter passing
    """
    if comment_type == "discussion":
        query_field = "discussions"
        query_comments_field = "comments"
    elif comment_type == "issue":
        query_field = "issues"
        query_comments_field = "comments"
    elif comment_type == "pullRequest":
        query_field = "pullRequests"
        query_comments_field = "comments"
    else:
        raise ValueError(f"Invalid comment type: {comment_type}")

    query = f"""
    query($owner: String!, $repo: String!, $first: Int, $after: String) {{
      repository(owner: $owner, name: $repo) {{
        {query_field}(first: 10) {{
          edges {{
            node {{
              id
              title
              {query_comments_field}(first: 10, after: $after) {{
                edges {{
                  node {{
                    id
                    body
                    isMinimized
                  }}
                  cursor
                }}
                pageInfo {{
                  endCursor
                  hasNextPage
                }}
              }}
            }}
          }}
          pageInfo {{
            hasNextPage
            endCursor
          }}
        }}
      }}
    }}
    """
    variables = {
        "owner": owner,
        "repo": repo,
        "first": 10,
        "after": after_cursor,
    }
    response = requests.post(GITHUB_API_URL, headers=headers, json={"query": query, "variables": variables})
    print(f"Fetch {comment_type} Comments Response:", response.json())  # Debugging line
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Query failed with code {response.status_code}. Response: {response.json()}")

def minimize_comment(comment_id, headers):
    mutation = """
    mutation($commentId: ID!) {
      minimizeComment(input: {subjectId: $commentId, classifier: SPAM}) {
        minimizedComment {
          isMinimized
          minimizedReason
        }
      }
    }
    """
    variables = {"commentId": comment_id}
    response = requests.post(GITHUB_API_URL, headers=headers, json={"query": mutation, "variables": variables})
    if response.status_code == 200:
        data = response.json()
        return data["data"]["minimizeComment"]["minimizedComment"]["isMinimized"]
    else:
        print(f"Failed to minimize comment with ID {comment_id}. Status code: {response.status_code}")
        return False

def detect_spam(comment_body):
    model = joblib.load("/app/spam_detector_model.pkl")  # Load new model pipeline directly
    return model.predict([comment_body])[0] == 1

def moderate_comments(owner, repo, token):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    spam_results = []
    comment_types = ["discussion", "issue", "pullRequest"]

    for comment_type in comment_types:
        # Try to load existing cursor from cache file if exists
        latest_cursor = None
        
        try:
            while True:
                # Pass comment_type as a parameter, not a keyword
                data = fetch_comments(owner, repo, headers, after_cursor=latest_cursor, comment_type=comment_type)
                
                # Select the correct comment type in the response
                comment_type_plural = comment_type + "s"
                
                for entity in data['data']['repository'][comment_type_plural]['edges']:
                    for comment_edge in entity['node']['comments']['edges']:
                        comment_id = comment_edge['node']['id']
                        comment_body = comment_edge['node']['body']
                        is_minimized = comment_edge['node']['isMinimized']

                        # Debugging outputs
                        print(f"Processing {comment_type} comment:", comment_body)
                        print("Is Minimized:", is_minimized)
                        print("Is Spam:", detect_spam(comment_body))

                        if not is_minimized and detect_spam(comment_body):
                            hidden = minimize_comment(comment_id, headers)
                            spam_results.append({"id": comment_id, "hidden": hidden})

                        latest_cursor = comment_edge['cursor']

                    page_info = entity['node']['comments']['pageInfo']
                    if not page_info['hasNextPage']:
                        break

                # Check if there are more comments for the current comment type
                if not data['data']['repository'][comment_type_plural]['pageInfo']['hasNextPage']:
                    break
                
                latest_cursor = data['data']['repository'][comment_type_plural]['pageInfo']["endCursor"]
                
                # Save cursor to a file for GitHub Actions cache
                save_cursor_to_cache(owner, repo, comment_type, latest_cursor)
        
        except Exception as e:
            print(f"Error processing {comment_type}s: " + str(e))
    
    print("Moderation Results:")
    print(spam_results)

if __name__ == "__main__":
    OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER") 
    REPO = os.environ.get("GITHUB_REPOSITORY")          
    TOKEN = os.getenv('GITHUB_TOKEN') 
    
    try:
        repo_parts = os.environ.get("GITHUB_REPOSITORY").split("/")  
        if len(repo_parts) == 2:  
            OWNER = repo_parts[0]
            REPO = repo_parts[1]
        else:
            raise ValueError("GITHUB_REPOSITORY environment variable is not in the expected 'owner/repo' format.")
    except (AttributeError, ValueError) as e:
        print(f"Error getting repository information: {e}")
        exit(1)  

    moderate_comments(OWNER, REPO, TOKEN)