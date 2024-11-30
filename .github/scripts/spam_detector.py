import joblib
import requests
import os
import json

GITHUB_API_URL = "https://api.github.com/graphql"
CURSOR_FILE = os.path.join(os.environ['GITHUB_WORKSPACE'], ".github", "spam_detector_cursor.txt")

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
    model = joblib.load("/app/spam_detector_model.pkl")
    return model.predict([comment_body])[0] == 1


def load_cursor():
    try:
        with open(CURSOR_FILE, "r") as f:
            cursors = json.load(f)
            return cursors
    except FileNotFoundError:
        return {"discussion": None, "issue": None, "pullRequest": None}

def save_cursor(cursors):
    with open(CURSOR_FILE, "w") as f:
        json.dump(cursors, f)


def moderate_comments(owner, repo, token):
    print(f"CURSOR_FILE inside moderate_comments: {CURSOR_FILE}")  # Debug print
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    spam_results = []
    comment_types = ["discussion", "issue", "pullRequest"]
    cursors = load_cursor()

    for comment_type in comment_types:
        latest_cursor = cursors.get(comment_type)
        try:
            while True:
                data = fetch_comments(owner, repo, headers, latest_cursor, comment_type=comment_type)

                # Data Validation (Improved)
                if not data or 'data' not in data or 'repository' not in data['data'] or comment_type + "s" not in data['data']['repository']:
                    print(f"Skipping {comment_type} due to invalid data.")
                    break # breaks from the while True loop. Continues to the next comment_type if there are any more

                if not data['data']['repository'][comment_type + "s"]['pageInfo']['hasNextPage']:
                    break # Breaks from the while True loop to the next comment_type.

                for entity in data['data']['repository'][comment_type + "s"]['edges']:
                    # Entity Validation
                    if 'node' not in entity or 'comments' not in entity['node'] or 'edges' not in entity['node']['comments']:
                        print(f"Invalid entity data for {comment_type}: {entity}")
                        continue # breaks from the entity loop to the next entity if available

                    for comment_edge in entity['node']['comments']['edges']:
                        # Comment Validation
                        if 'node' not in comment_edge or 'id' not in comment_edge['node'] or 'body' not in comment_edge['node'] or 'isMinimized' not in comment_edge['node']:
                            print(f"Invalid comment data for {comment_type}: {comment_edge}")
                            continue # breaks from the current comment loop to the next comment if available

                        comment_id = comment_edge['node']['id']
                        comment_body = comment_edge['node']['body']
                        is_minimized = comment_edge['node']['isMinimized']

                        print(f"Processing {comment_type} comment:", comment_body)
                        print("Is Minimized:", is_minimized)
                        print("Is Spam:", detect_spam(comment_body))

                        if not is_minimized and detect_spam(comment_body):
                            hidden = minimize_comment(comment_id, headers)
                            spam_results.append({"id": comment_id, "hidden": hidden})

                        latest_cursor = comment_edge['cursor'] # Only place where latest_cursor is updated

                # Update and save cursor after processing all comments on the current page:
                cursors[comment_type] = latest_cursor if latest_cursor else data['data']['repository'][comment_type + "s"]['pageInfo']['endCursor']
                save_cursor(cursors)


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