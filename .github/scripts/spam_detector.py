import joblib
import requests
import os
import json

GITHUB_API_URL = "https://api.github.com/graphql"
CACHE_DIR = '.github/cursor_cache'
CACHE_FILE = f'{CACHE_DIR}/cursor.json'

def load_cursor():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cursor cache: {e}")
    return {}

def save_cursor(cursor_data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cursor_data, f)
        print(f"Cursor saved: {cursor_data}")
    except Exception as e:
        print(f"Error saving cursor cache: {e}")

def fetch_comments(owner, repo, headers, after_cursor=None, comment_type="discussion"):
    query_field = {
        "discussion": "discussions",
        "issue": "issues",
        "pullRequest": "pullRequests"
    }.get(comment_type, "discussions")
    query = f"""
    query($owner: String!, $repo: String!, $first: Int, $after: String) {{
      repository(owner: $owner, name: $repo) {{
        {query_field}(first: 10, after: $after) {{
          edges {{
            node {{
              id
              title
              comments(first: $first, after: $after) {{
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
    print("Fetch Comments Response:", response.json())
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
    
    cursor_data = load_cursor()
    print(f"Loaded cursor data: {cursor_data}")

    for comment_type in comment_types:
        latest_cursor = cursor_data.get(comment_type)
        try:
            while True:
                data = fetch_comments(owner, repo, headers, latest_cursor, comment_type=comment_type)
                comments = data['data']['repository'][comment_type + "s"]['edges']
                
                if not comments:
                    break

                for entity in comments:
                    for comment_edge in entity['node']['comments']['edges']:
                        comment_id = comment_edge['node']['id']
                        comment_body = comment_edge['node']['body']
                        is_minimized = comment_edge['node']['isMinimized']

                        print(f"Processing {comment_type} comment:", comment_body)
                        print("Is Minimized:", is_minimized)
                        print("Is Spam:", detect_spam(comment_body))

                        if not is_minimized and detect_spam(comment_body):
                            hidden = minimize_comment(comment_id, headers)
                            spam_results.append({"id": comment_id, "hidden": hidden})

                        latest_cursor = comment_edge['cursor']

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break
                latest_cursor = data['data']['repository'][comment_type + "s"]['pageInfo']["endCursor"]
        
        except Exception as e:
            print(f"Error processing {comment_type}s: " + str(e))
        
        cursor_data[comment_type] = latest_cursor
    
    save_cursor(cursor_data)
    
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