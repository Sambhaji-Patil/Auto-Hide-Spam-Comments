import joblib
import requests
import os
import json
import hashlib

GITHUB_API_URL = "https://api.github.com/graphql"
CURSOR_CACHE_FILE = "/tmp/spam_detection_cursor.json"

def save_cursor(cursor_data):
    """Save cursor data to a cache file."""
    try:
        # Create a unique identifier based on repo and comment type
        unique_id = hashlib.md5(f"{cursor_data['owner']}{cursor_data['repo']}{cursor_data['comment_type']}".encode()).hexdigest()
        cursor_data['unique_id'] = unique_id
        
        with open(CURSOR_CACHE_FILE, 'w') as f:
            json.dump(cursor_data, f)
        
        print(f"Cursor saved: {cursor_data}")
        return True
    except Exception as e:
        print(f"Error saving cursor: {e}")
        return False

def load_cursor(owner, repo, comment_type):
    """Load cursor from cache file if exists."""
    try:
        if not os.path.exists(CURSOR_CACHE_FILE):
            return None
        
        with open(CURSOR_CACHE_FILE, 'r') as f:
            cursor_data = json.load(f)
        
        # Validate loaded cursor matches current repo and comment type
        if (cursor_data.get('owner') == owner and 
            cursor_data.get('repo') == repo and 
            cursor_data.get('comment_type') == comment_type):
            print(f"Loaded cursor: {cursor_data}")
            return cursor_data['cursor']
        
        return None
    except Exception as e:
        print(f"Error loading cursor: {e}")
        return None

def fetch_comments(owner, repo, headers, comment_type="discussion", after_cursor=None):
    if comment_type == "discussion":
        query_field = "discussions"
        query_comments_field = "comments"
    elif comment_type == "issue":
        query_field = "issues"
        query_comments_field = "comments"
    elif comment_type == "pullRequest":
        query_field = "pullRequests"
        query_comments_field = "comments"

    query = f"""
    query($owner: String!, $repo: String!, $first: Int, $after: String) {{
      repository(owner: $owner, name: $repo) {{
        {query_field}(first: 10) {{
          edges {{
            node {{
              id
              title
              {query_comments_field}(first: $first, after: $after) {{
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
    print("Fetch Comments Response:", response.json())  # Debugging line
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
        # Try to load existing cursor
        latest_cursor = load_cursor(owner, repo, comment_type)
        
        try:
            while True:
                data = fetch_comments(owner, repo, headers, latest_cursor, comment_type=comment_type)
                for entity in data['data']['repository'][comment_type + "s"]['edges']:
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

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break
                latest_cursor = data['data']['repository'][comment_type + "s"]['pageInfo']["endCursor"]
                
                # Save cursor for next iteration
                save_cursor({
                    'owner': owner,
                    'repo': repo,
                    'comment_type': comment_type,
                    'cursor': latest_cursor
                })
        
        except Exception as e:
            print(f"Error processing {comment_type}s: " + str(e))
    
    # Optional: Remove the cursor file after processing
    try:
        os.remove(CURSOR_CACHE_FILE)
    except Exception as e:
        print(f"Could not remove cursor cache file: {e}")
    
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