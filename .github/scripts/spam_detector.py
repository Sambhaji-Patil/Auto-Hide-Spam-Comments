import joblib
import requests
import os

GITHUB_API_URL = "https://api.github.com/graphql"

# Cursor Management
def read_last_cursor(cursor_file):
    """Read the last saved cursor from the file."""
    try:
        with open(cursor_file, "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return None

def save_last_cursor(cursor_file, cursor):
    """Save the current cursor to the file."""
    os.makedirs(os.path.dirname(cursor_file), exist_ok=True)
    with open(cursor_file, "w") as file:
        file.write(cursor)
    print(f"Cursor updated to: {cursor}")

# Fetch Comments
def fetch_comments(owner, repo, headers, after_cursor=None, comment_type="discussion"):
    query_field = {
        "discussion": "discussions",
        "issue": "issues",
        "pullRequest": "pullRequests"
    }[comment_type]
    comments_field = "comments"

    query = f"""
    query($owner: String!, $repo: String!, $first: Int, $after: String) {{
      repository(owner: $owner, name: $repo) {{
        {query_field}(first: 10, after: $after) {{
          edges {{
            node {{
              id
              title
              {comments_field}(first: $first, after: $after) {{
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

# Minimize Comment
def minimize_comment(comment_id, headers):
    """Minimize a comment by marking it as spam."""
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

# Detect Spam
def detect_spam(comment_body):
    """Detect if a comment is spam using a pretrained model."""
    model = joblib.load("/app/spam_detector_model.pkl")
    return model.predict([comment_body])[0] == 1

# Moderate Comments
def moderate_comments(owner, repo, token):
    """Moderate comments by fetching, detecting spam, and minimizing spam comments."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    spam_results = []
    comment_types = ["discussion", "issue", "pullRequest"]
    cursor_file = os.getenv("CURSOR_FILE", "last_cursor.txt")

    for comment_type in comment_types:
        latest_cursor = read_last_cursor(cursor_file)
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
                            minimize_comment(comment_id, headers)
                            spam_results.append({"id": comment_id})

                        # Update and save the latest cursor
                        latest_cursor = comment_edge['cursor']
                        save_last_cursor(cursor_file, latest_cursor)

                    page_info = entity['node']['comments']['pageInfo']
                    if not page_info['hasNextPage']:
                        break

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break
        
        except Exception as e:
            print(f"Error processing {comment_type}s: {e}")

    print("Moderation Results:", spam_results)

if __name__ == "__main__":
    try:
        repo_parts = os.environ.get("GITHUB_REPOSITORY").split("/")  
        if len(repo_parts) == 2:  
            OWNER, REPO = repo_parts
        else:
            raise ValueError("GITHUB_REPOSITORY environment variable is not in the expected 'owner/repo' format.")
    except (AttributeError, ValueError) as e:
        print(f"Error getting repository information: {e}")
        exit(1)  

    TOKEN = os.getenv('GITHUB_TOKEN')
    moderate_comments(OWNER, REPO, TOKEN)
