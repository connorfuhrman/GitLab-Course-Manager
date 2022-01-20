"""@package docstring
Main file in the Gitlab-Course-Manager (gcm) package responsible for connecting to Gitlab and manipulating
for the purpose of posting and autograding student coding assignments."""

import gitlab
import pandas as pd
import os, sys, subprocess
import logging
import configparser as cp
import json


###### "Private" helper methods that really don't need to be called from outside this package ######

"""Lambda helper to expand the default settings path or the path provided by the argument
@param f Path to the params file or None. If None default of ~/.gcm/settings.ini will be used"""
_get_config_file = lambda f : os.path.expanduser("~/.gcm/settings.ini") if f is  None else os.path.expanduser(f)

def _get_auth_info(config_file = None) -> dict :
    """Helper function to get the URL and PA token from the settings file. 
    @param settings_file Full path to the config file. This can be updated in a fork
    to use a different format for initialization so long as the dictionary returned has
    the correct key-value pairs."""
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    if not 'setup' in settings:
        raise ValueError(f"File {config_file} must contain a section '[setup]'")
    setup = settings['setup']
    if not 'url' in setup:
        raise ValueError(f"File {config_file} must contain an entry 'url' in the '[setup]' section")
    if not 'pa_token' in setup:
        raise ValueError(f"File {config_file} must contain an entry 'pa_token' in the '[setup]' section")
    logging.debug(f"Got URl as {setup['url']}")

    return {'url' : setup['url'], 'pa_token' : setup['pa_token']}



def _get_groups_info(config_file = None) -> dict:
    """Helper function to get the student group ID for the top-level student groups
    @params config_file Full path to the config file. """
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    if not 'groups' in settings:
        raise ValueError(f"File {config_file} must contain a section '[groups]'")
    group_set = settings['groups']
    if not 'student_group_id' in group_set:
        raise ValueError(f"File {config_file} must contain an entry 'student_group_id' in the '[group]' section")
    logging.debug(f"Got student group ID as {group_set['student_group_id']}")
    
    return {'student_group_id' : int(group_set['student_group_id'])}


def _get_course_info(config_file = None) -> dict :
    """Helper function to get the configuration parameters related to the course
    @params config_file Path to the config file"""
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    if not 'course' in settings:
        raise ValueError(f"File {config_file} must contain a section '[course]'")
    course_set = settings['course']
    if not 'roster' in course_set:
        raise ValueError(f"File {config_file} must contain an entry 'roster' in the '[course]' section")
    roster_f = course_set['roster']
    logging.debug(f"Got course roster {roster_f}")

    return {'roster' : roster_f}



def _get_toplevel_student_group(gl, config_file = None):
    """Helper function to get the top-level student group where each subgroup corresponts to one 
    student in the course
    @param gl The GitLab object which has been authenticated via connect 
    @param config_file Optional path to the configuration file"""
    id = _get_groups_info(config_file)['student_group_id']
    logging.debug(f"Getting GitLab group object for ID {id}")
    
    return gl.groups.get(id, lazy=True)


"""Helper function (which can be updated in, e.g., a fork) to read the roster into a Pandas
DataFrame. I use an Excel file but anything that can be read into a df should work later. 
@params f The file to read"""
_read_course_roster = lambda f : pd.read_excel(f)

"""Helper function (which can be updated in, e.g., a fork) to get the student's first name
from their row in the Pandas DataFrame
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_firstname = lambda s : s['First Name']

"""Helper function (which can be updated in, e.g., a fork) to get the student's last name
from their row in the Pandas DataFrame
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_lastname = lambda s : s['Last Name']

"""Helper function (which can be updated in, e.g., a fork) to get the student group name
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_groupname = lambda s : _get_student_firstname(s) + " " + _get_student_lastname(s)

"""Helper function (which can be updated in, e.g., a fork) to get the student group path
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_grouppath = lambda s : f"{_get_student_firstname(s)}-{_get_student_lastname(s)}".replace(' ', '-').lower()


_get_student_username = lambda s : s['Username']

def _get_course_roster(config_file = None) -> pd.DataFrame :
    """Helper function to read the course roster from the configuration file
    @param config_file Optional path to the configuration file"""
    roster_f = _get_course_info(config_file)['roster']
    roster = _read_course_roster(roster_f)

    return roster


def _get_student_user_id(gl, student) -> int :
    user = gl.users.list(search=_get_student_username(student))
    id = None
    for u in user:
        if u.username == _get_student_username(student):
            id = u.id
            break
    if id is None:
        raise ValueError(f"Could not find username for {_get_student_firstname(s)} {_get_student_lastname(s)}")
    return id


###### "Public" package methods ######

def connect(settings_file = None) -> None:
    """Function to establish connection to Gitlab. 
    @param settings_path Optional path to the settings.ini file. Default is ~/.gcm/settings.ini"""
    config_file = os.path.expanduser("~/.gcm/settings.ini") if settings_file is None else settings_file
    logging.debug(f"Got settings path of {config_file}")
    setup = _get_auth_info(config_file)
    logging.debug("Attempting to connect to GitLab ...")
    gl = gitlab.Gitlab(setup['url'], private_token=setup['pa_token'], api_version=4)
    gl.auth()

    return gl


def make_student_groups(gl, settings_file = None, access_level = gitlab.MAINTAINER_ACCESS) -> None:
    """Function to create student groups where each student group houses all "projects" which are each student's 
    assignments. Each group named according to the function _get_student_groupname
    @params gl The authenticated GitLab object 
    @params settings_file The path to the confuration file"""
    roster = _get_course_roster(settings_file)
    for i, student in roster.iterrows():
        groupname = _get_student_groupname(student)
        group_to_create = {
            'name' : groupname,
            'visibility' : 'private',
            'path' : _get_student_grouppath(student),
            'parent_id' : _get_groups_info(settings_file)['student_group_id']
        }
        logging.debug(f"Creating group\n{json.dumps(group_to_create, sort_keys=False, indent=2)}")
        #group = gl.groups.create(group_to_create, retry_transient_errors = True)
        member_to_add = {
            'username' : _get_student_username(student),
            'access_level' : access_level,
            'user_id' : _get_student_user_id(gl, student)
        }
        #member = group.members.create(member_to_add, retry_transient_errors = True)
            



##### Function for local testing #####
def _localtest(file = None):
    gl = connect(file)
    make_student_groups(gl, file)



if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    _localtest()
