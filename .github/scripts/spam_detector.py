import joblib
import requests
import os
from pathlib import Path

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

def get_cursor_file(cursor_dir):
    return Path(cursor_dir) / "last_cursor.txt"

def read_cursor(cursor_file):
    if cursor_file.exists():
        with open(cursor_file, "r") as file:
            return file.read().strip()
    return None

def save_cursor(cursor, cursor_file):
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cursor_file, "w") as file:
        file.write(cursor)

def moderate_comments(owner, repo, token):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    cursor_dir = "/app/.github/cache"
    cursor_file = get_cursor_file(cursor_dir)
    latest_cursor = read_cursor(cursor_file)

    # Debug: Check if cursor exists
    print(f"Latest cursor: {latest_cursor}")

    if latest_cursor is None:
        print("No cursor found, starting fresh.")

    spam_results = []
    comment_types = ["discussion", "issue", "pullRequest"]

    for comment_type in comment_types:
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

                        # Update cursor
                        latest_cursor = comment_edge['cursor']

                    page_info = entity['node']['comments']['pageInfo']
                    if not page_info['hasNextPage']:
                        break

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break
        
        except Exception as e:
            print(f"Error processing {comment_type}s: " + str(e))
            break
    
    # Save the latest cursor
    if latest_cursor:
        save_cursor(latest_cursor, cursor_file)

    print("Moderation Results:")
    print(spam_results)

if __name__ == "__main__":
    OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER")
    REPO = os.environ.get("GITHUB_REPOSITORY")
    TOKEN = os.getenv('GITHUB_TOKEN')
    
    if not OWNER or not REPO or not TOKEN:
        print("Missing necessary environment variables.")
        exit(1)

    moderate_comments(OWNER, REPO, TOKEN)
