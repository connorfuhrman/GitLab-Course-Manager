import os

"""Lambda helper to sort out issues with paths"""
path = lambda p : os.path.normpath(os.path.expanduser(p))
