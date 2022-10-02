def initial_write(JIRA_COMMENT_STR):
    f= open("comment.txt","w+")
    f.write(JIRA_COMMENT_STR)
    f.close()

def append_comment(JIRA_COMMENT_STR: dict):
    f= open("comment.txt","a+")
    f.write(JIRA_COMMENT_STR)
    f.close()

def read_comment():
    f=open("comment.txt", "r")
    r_comment =f.read()
    f.close()
    return r_comment