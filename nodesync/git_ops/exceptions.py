"""
Git exception types.
"""


class GitError(Exception):
    pass


class GitNotFoundError(GitError):
    pass
