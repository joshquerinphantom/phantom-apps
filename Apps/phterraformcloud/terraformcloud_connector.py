# File: terraformcloud_connector.py
# Copyright (c) 2019-2020 Splunk Inc.
#
# SPLUNK CONFIDENTIAL – Use or disclosure of this material in whole or in part
# without a valid written license from Splunk Inc. is PROHIBITED.

# Phantom App imports
import phantom.app as phantom
from phantom.base_connector import BaseConnector
from phantom.action_result import ActionResult

from terraformcloud_consts import *
import requests
import json
from bs4 import BeautifulSoup


class RetVal(tuple):
    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class TerraformCloudConnector(BaseConnector):

    def __init__(self):

        # Call the BaseConnectors init first
        super(TerraformCloudConnector, self).__init__()

        self._state = None

        # Variable to hold a base_url in case the app makes REST calls
        # Do note that the app json defines the asset config, so please
        # modify this as you deem fit.
        self._base_url = None

    def _process_empty_response(self, response, action_result):

        if response.status_code == 200:
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(action_result.set_status(phantom.APP_ERROR, "Empty response and no information in the header"), None)

    def _process_html_response(self, response, action_result):

        # An html response, treat it like an error
        status_code = response.status_code

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            error_text = soup.text
            split_lines = error_text.split('\n')
            split_lines = [x.strip() for x in split_lines if x.strip()]
            error_text = '\n'.join(split_lines)
        except:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(status_code,
                error_text)

        message = message.replace('{', '{{').replace('}', '}}')

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):

        # Try a json parse
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response. Error: {0}".format(str(e))), None)

        # Please specify the status codes here
        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        # You should process the error returned in the json
        message = "Error from server. Status Code: {0} Data from server: {1}".format(
                r.status_code, r.text.replace('{', '{{').replace('}', '}}'))

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):

        # store the r_text in debug data, it will get dumped in the logs if the action fails
        if hasattr(action_result, 'add_debug_data'):
            action_result.add_debug_data({'r_status_code': r.status_code})
            action_result.add_debug_data({'r_text': r.text})
            action_result.add_debug_data({'r_headers': r.headers})

        # Process each 'Content-Type' of response separately

        # Process a json response
        if 'json' in r.headers.get('Content-Type', ''):
            return self._process_json_response(r, action_result)

        # Process an HTML response, Do this no matter what the api talks.
        # There is a high chance of a PROXY in between phantom and the rest of
        # world, in case of errors, PROXY's return HTML, this function parses
        # the error and adds it to the action_result.
        if 'html' in r.headers.get('Content-Type', ''):
            return self._process_html_response(r, action_result)

        # it's not content-type that is to be parsed, handle an empty response
        if not r.text:
            return self._process_empty_response(r, action_result)

        # everything else is actually an error at this point
        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
                r.status_code, r.text.replace('{', '{{').replace('}', '}}'))

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _make_rest_call(self, endpoint, action_result, method="get", headers=None, **kwargs):
        # **kwargs can be any additional parameters that requests.request accepts

        config = self.get_config()

        resp_json = None

        _headers = {
            "authorization": "Bearer {}".format(self._auth_token)
        }
        
        if headers:
            _headers.update(headers)

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(action_result.set_status(phantom.APP_ERROR, "Invalid method: {0}".format(method)), resp_json)

        # Create a URL to connect to
        url = self._base_url + endpoint

        try:
            r = request_func(
                            url,
                            verify=config.get('verify_server_cert', False),
                            headers=_headers,
                            **kwargs)
        except Exception as e:
            return RetVal(action_result.set_status( phantom.APP_ERROR, "Error Connecting to server. Details: {0}".format(str(e))), resp_json)

        return self._process_response(r, action_result)

    def _handle_test_connectivity(self, param):

        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Connecting to acount details endpoint...")
        
        # make rest call
        ret_val, response = self._make_rest_call(TERRAFORM_ENDPOINT_ACCOUNT_DETAILS, action_result)

        if (phantom.is_fail(ret_val)):
            self.save_progress("Test Connectivity Failed.")
            return action_result.get_status()

        # Return success
        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_workspaces(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        organization_name = param['organization_name']
        page_num = param.get('page_num', 1)
        page_size = param.get('page_size', 100)
        
        params = {
            'page[num]': page_num,
            'page[size]': page_size
        }

        self.save_progress("Params: {}".format(params))

        endpoint = TERRAFORM_ENDPOINT_WORKSPACES.format(organization_name=organization_name)

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result, params=params)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response)

        # summary = action_result.update_summary({})
        # summary['num_data'] = len(action_result['data'])

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_list_runs(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        workspace_id = param['id']
        page_num = param.get('page_num', 1)
        page_size = param.get('page_size', 20)
        
        params = {
            'page[num]': page_num,
            'page[size]': page_size
        }

        endpoint = TERRAFORM_ENDPOINT_LIST_RUNS.format(id=workspace_id)

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result, params=params)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response)

        # summary = action_result.update_summary({})
        # summary['num_data'] = len(action_result['data'])

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_create_run(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        workspace_id = param['workspace_id']
        configuration_version = param.get('configuration_version')
        message = param.get('message')
        is_destroy = param.get('is_destroy', False)

        params = {
            "data": {
                "attributes": {
                    "is-destroy": is_destroy,
                    "message": message
                }
            },
            "relationships": {
                "workspace": {
                    "data": {
                        "type": "workspaces",
                        "id": workspace_id
                    }
                }
            },
            "configuration-version": {
                "data": {
                    "type": "configuration-versions",
                    "id": configuration_version
                }
            }
        }
        
        headers = {
            'Content-Type': 'application/vnd.api+json'
        }

        # make rest call
        ret_val, response = self._make_rest_call(TERRAFORM_ENDPOINT_RUNS, action_result, method="post", headers=headers, json=params)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response)

        # summary = action_result.update_summary({})
        # summary['num_data'] = len(action_result['data'])

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_create_workspace(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        organization_name = param['organization_name']

        post_data = {
            'type': 'workspaces',
            'attributes': {
                'name': param['workspace_name']
            }
        }

        if param.get('description'):
            post_data['attributes']['description'] = param['description']

        if param.get('vcs_repo_id'):
            # both repo id and token id are required
            if not param.get('vcs_token_id'):
                return action_result.set_status(phantom.APP_ERROR, "IF a VCS repo is to be linked to this workspace, both the repository ID and the token ID are required.")

            post_data['attributes']['vcs-repo'] = {
                'identifier': param.get('vcs_repo_id'),
                'oauth-token-id': param.get('vcs_token_id')
            }

        post_data['attributes']['file-triggers-enabled'] = param.get('file_triggers_enabled', True)
        post_data['attributes']['auto-apply'] = param.get('auto_apply', False)
        post_data['attributes']['queue-all-runs'] = param.get('queue_all_runs', False)
        post_data = {
            'data': post_data
        }
        endpoint = TERRAFORM_ENDPOINT_WORKSPACES.format(organization_name=organization_name)

        headers = {
            'Content-Type': 'application/vnd.api+json'
        }

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result, method="post", headers=headers, json=post_data)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        resp_data = response.get('data', {})

        action_result.add_data(resp_data)

        summary = action_result.update_summary({})
        summary['workspace_id'] = resp_data.get('id')

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_apply_run(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        run_id = param['id']
        comment = param.get('comment')

        params = {}

        if comment:
            params['comment'] = comment
        
        headers = {
            'Content-Type': 'application/vnd.api+json'
        }

        endpoint = TERRAFORM_ENDPOINT_APPLY_RUN.format(run_id=run_id)

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result, method="post", headers=headers, json=params)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response)

        # summary = action_result.update_summary({})
        # summary['num_data'] = len(action_result['data'])

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_get_apply(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        id = param['id']

        endpoint = TERRAFORM_ENDPOINT_APPLIES.format(id=id)

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response)

        # summary = action_result.update_summary({})
        # summary['num_data'] = len(action_result['data'])

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_get_plan(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        id = param['id']

        endpoint = TERRAFORM_ENDPOINT_PLANS.format(id=id)

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response.get('data', {}))

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_get_run(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        id = param['id']

        endpoint = TERRAFORM_ENDPOINT_RUNS + "/" + id

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response.get('data', {}))

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_get_workspace(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        action_result = self.add_action_result(ActionResult(dict(param)))

        if param.get('id'):
            endpoint = TERRAFORM_ENDPOINT_GET_WORKSPACE_BY_ID.format(id=param.get('id'))
        elif param.get('organization_name') and param.get('workspace_name'):
            endpoint = TERRAFORM_ENDPOINT_WORKSPACES.format(organization_name=param.get('organization_name')) + "/" + param.get('workspace_name')
        else:
            return action_result.set_status(phantom.APP_ERROR, "Both the organization name and workspace name must be provided.")

        # make rest call
        ret_val, response = self._make_rest_call(endpoint, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()
            
        action_result.add_data(response.get('data', {}))

        return action_result.set_status(phantom.APP_SUCCESS)

    def handle_action(self, param):

        ret_val = phantom.APP_SUCCESS

        # Get the action that we are supposed to execute for this App Run
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if action_id == 'test_connectivity':
            ret_val = self._handle_test_connectivity(param)

        elif action_id == 'list_workspaces':
            ret_val = self._handle_list_workspaces(param)

        elif action_id == 'list_runs':
            ret_val = self._handle_list_runs(param)        

        elif action_id == 'create_run':
            ret_val = self._handle_create_run(param)

        elif action_id == 'create_workspace':
            ret_val = self._handle_create_workspace(param)

        elif action_id == 'apply_run':
            ret_val = self._handle_apply_run(param)

        elif action_id == 'get_apply':
            ret_val = self._handle_get_apply(param)

        elif action_id == 'get_plan':
            ret_val = self._handle_get_plan(param)

        elif action_id == 'get_run':
            ret_val = self._handle_get_run(param)
        
        elif action_id == 'get_workspace':
            ret_val = self._handle_get_workspace(param)

        return ret_val

    def initialize(self):

        # Load the state in initialize, use it to store data
        # that needs to be accessed across actions
        self._state = self.load_state()

        # get the asset config
        config = self.get_config()

        # base URL
        self._base_url = config.get('base_url', TERRAFORM_DEFAULT_URL).strip('/')
        self._base_url += TERRAFORM_BASE_API_ENDPOINT

        # token
        self._auth_token = config["token"]

        return phantom.APP_SUCCESS

    def finalize(self):

        # Save the state, this data is saved across actions and app upgrades
        self.save_state(self._state)
        return phantom.APP_SUCCESS


if __name__ == '__main__':

    import pudb
    import argparse

    pudb.set_trace()

    argparser = argparse.ArgumentParser()

    argparser.add_argument('input_test_json', help='Input Test JSON file')
    argparser.add_argument('-u', '--username', help='username', required=False)
    argparser.add_argument('-p', '--password', help='password', required=False)

    args = argparser.parse_args()
    session_id = None

    username = args.username
    password = args.password

    if (username is not None and password is None):

        # User specified a username but not a password, so ask
        import getpass
        password = getpass.getpass("Password: ")

    if (username and password):
        try:
            login_url = TerraformCloudConnector._get_phantom_base_url() + '/login'

            print ("Accessing the Login page")
            r = requests.get(login_url, verify=False)
            csrftoken = r.cookies['csrftoken']

            data = dict()
            data['username'] = username
            data['password'] = password
            data['csrfmiddlewaretoken'] = csrftoken

            headers = dict()
            headers['Cookie'] = 'csrftoken=' + csrftoken
            headers['Referer'] = login_url

            print ("Logging into Platform to get the session id")
            r2 = requests.post(login_url, verify=False, data=data, headers=headers)
            session_id = r2.cookies['sessionid']
        except Exception as e:
            print(("Unable to get session id from the platform. Error: " + str(e)))
            exit(1)

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print((json.dumps(in_json, indent=4)))

        connector = TerraformCloudConnector()
        connector.print_progress_message = True

        if (session_id is not None):
            in_json['user_session_token'] = session_id
            connector._set_csrf_info(csrftoken, headers['Referer'])

        ret_val = connector._handle_action(json.dumps(in_json), None)
        print((json.dumps(json.loads(ret_val), indent=4)))

    exit(0)