import git
import os
import sys


def git_puller():
    """Pulls the latest version of this script from Git.
    Exits the script with an error if we are not already on the latest version."""


    path = os.getcwd()
    repo = git.Repo(path)

    if 'main' in repo.branches:
        branch = 'main'
    else:
        branch = 'master'

    current_hash = repo.head.object.hexsha
    o = repo.remotes.origin
    o.fetch()
    changed = o.refs[branch].object.hexsha != current_hash
    if os.environ.get("SKIP_GIT_CHECK") == "1":
        changed = False
    if changed:
        try:
            git.cmd.Git(path).pull()
            sys.exit("Script has been updated please re-run")
        except Exception as e:
            sys.exit('git pull failed try running manually')
    sha = repo.git.rev_parse(current_hash, short=8)
    return sha
def shc_testing():
    return bool(os.environ.get("TEST_KV_MIG_SHC_ENABLED") == "1")