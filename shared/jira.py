from getpass import getpass, getuser

#Hardcode of jira_cloud var
jira_cloud = False
if jira_cloud:
    from atlassian import Jira
else:
    from jira import JIRA


def start_implementation(ticket_id: str):
    """Prompts for Jira login credentials and attempts to set the given ticket to IMPLEMENTATION status

    Parameters
    ----------
    ticket_id: str
        Jira ticket ID to update
    """
    print("Please enter your Splunk (not SplunkCloud) Okta credentials to connect to Jira.")
    username = getuser()
    password = getpass(f"Password for {username}: ")

    jira_client = JIRA(server="https://jira.splunk.com", basic_auth=(username, password))

    jira_status: str = jira_client.issue(ticket_id).raw["fields"]["status"]["name"]

    if jira_status.upper() in ["SCHEDULED", "ON HOLD"]:
        jira_client.transition_issue(ticket_id, transition="Start Implementation", fields={
            "assignee": {
                "name": username
            }
        })
    elif jira_status == "IMPLEMENTATION":
        print("Jira is already in IMPLEMENTATION state, no change needed")
    else:
        print(f"Jira ticket is in {jira_status} state. Please remember to put it into IMPLEMENTATION state.")
        input("Press enter to continue.")
        
def start_implementation_jiracloud(ticket_id: str):
    # https://cd.splunkdev.com/splunkcloud-sre/sre-misc/techops-onboarding-jira-automation/-/blob/to_116854_jira_cloud_uat/create_epic.py
    print("Please enter your Splunk (not SplunkCloud) Okta credentials to connect to Jira.")
    username = getuser()
    password = getpass(f"Password for {username}: ")

    jira_client = Jira(server="https://jira.splunk.com", basic_auth=(username, password))

    jira_status: str = jira_client.issue(ticket_id).raw["fields"]["status"]["name"]

    if jira_status.upper() in ["SCHEDULED", "ON HOLD"]:
        jira_client.transition_issue(ticket_id, transition="Start Implementation", fields={
            "assignee": {
                "name": username
            }
        })
    elif jira_status == "IMPLEMENTATION":
        print("Jira is already in IMPLEMENTATION state, no change needed")
    else:
        print(f"Jira ticket is in {jira_status} state. Please remember to put it into IMPLEMENTATION state.")
        input("Press enter to continue.")