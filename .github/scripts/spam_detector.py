import os
import time
import joblib
import requests

GITHUB_API_URL = "https://api.github.com/graphql"

def fetch_comments(owner, repo, headers, after_cursor=None, comment_type="discussion"):
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
    model = joblib.load("/app/spam_detector_model.pkl")  
    return model.predict([comment_body])[0] == 1

def save_cursor(cursor, base_dir):
    timestamp = int(time.time())  
    cursor_file_path = os.path.join(base_dir, f"cursor_{timestamp}.txt")
    with open(cursor_file_path, "w") as f:
        f.write(cursor)
    print(f"Saved cursor to {cursor_file_path}")

def get_last_cursor(base_dir):
    try:
        cursor_files = sorted(
            [f for f in os.listdir(base_dir) if f.startswith("cursor_")],
            key=lambda x: int(x.split("_")[1].split(".")[0]),
            reverse=True
        )
        if cursor_files:
            with open(os.path.join(base_dir, cursor_files[0]), "r") as f:
                return f.read().strip()
    except Exception as e:
        print(f"Error fetching last cursor: {e}")
    return None

def moderate_comments(owner, repo, token, cursor_dir):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    spam_results = []
    comment_types = ["discussion", "issue", "pullRequest"]

    for comment_type in comment_types:
        latest_cursor = get_last_cursor(cursor_dir)
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
                        save_cursor(latest_cursor, cursor_dir)

                    page_info = entity['node']['comments']['pageInfo']
                    if not page_info['hasNextPage']:
                        break

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break
        
        except Exception as e:
            print(f"Error processing {comment_type}s: " + str(e))
    
    print("Moderation Results:")
    print(spam_results)

if __name__ == "__main__":
    OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER") 
    REPO = os.environ.get("GITHUB_REPOSITORY")          
    TOKEN = os.getenv('GITHUB_TOKEN')
    CURSOR_DIR = os.getenv("CURSOR_DIR", "/app/cursor_storage")
    os.makedirs(CURSOR_DIR, exist_ok=True)

    moderate_comments(OWNER, REPO, TOKEN, CURSOR_DIR)
