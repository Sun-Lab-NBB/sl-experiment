import os
import yaml

import globus_sdk
from collections import deque


#######################
# Globus Authentication
#######################

def get_config_path(path=''):
    """Get the path to the configuration file.

    Args:
        path (str, optional): Path to append to the configuration directory. Defaults to ''.

    Returns:
        str: The full path to the configuration file.
    """
    path = os.path.expanduser(os.path.join("~", ".sl-mesoscope", path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def get_uuids(configbasepath, uuidsname="globus-uuids.yml"):
    with open(os.path.join(configbasepath, uuidsname), 'r') as f:
        UUIDs = yaml.safe_load(f)
    return UUIDs

def globus_auth_client(client_id, refresh_tokens=True, scopes=globus_sdk.scopes.TransferScopes.all):
    """Obtain and return a Globus NativeAppAuthClient configured with RefreshTokenAuthorizer.

    Args:
        client_id (str): The Globus Native App Client ID.
        refresh_tokens (bool, optional): Whether to request refresh tokens. Defaults to True.
        scopes (str, optional): The scope to request. Defaults to globus_sdk.scopes.TransferScopes.all.

    Returns:
        globus_sdk.NativeAppAuthClient: A configured NativeAppAuthClient instance.
    """
    client = globus_sdk.NativeAppAuthClient(client_id)
    client.oauth2_start_flow(refresh_tokens=refresh_tokens, requested_scopes=scopes)
    return client

def globus_token(
        client=None,
        client_id=None,
        scopes=globus_sdk.scopes.TransferScopes.all,
        configname="globus-token.yml"
    ):  # noqa: ANN001
    """Get a Globus access token using the provided NativeAppAuthClient.

    Args:
        client (globus_sdk.NativeAppAuthClient, optional): A NativeAppAuthClient instance. Defaults to None.

    Returns:
        str: The Globus access token.
    """
    if client is None:
        client = globus_auth_client(client_id, scopes=scopes)
    print(f"Please go to this URL and login: {client.oauth2_get_authorize_url()}")
    auth_code = input("Please enter the code here: ").strip()
    token_response = client.oauth2_exchange_code_for_tokens(auth_code)
    transfer_tokens = token_response.by_resource_server['transfer.api.globus.org']

    data = {
        "transfer_rt": transfer_tokens["refresh_token"],
        "transfer_at": transfer_tokens["access_token"],
        "expires_at_s": transfer_tokens["expires_at_seconds"],
    }
    path = get_config_path(configname)
    with open(path, "w") as f:
        yaml.safe_dump(data, f)

    return token_response.by_resource_server["transfer.api.globus.org"]["access_token"]

#######################
# Globus Transfer
#######################

def globus_transfer_rt(basename="globus-token.yml", key="transfer_rt"):
    """Get the Globus refresh token from the configuration file.

    Returns:
        str: The Globus refresh token.
    """
    path = get_config_path(basename)
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
    return data.get(key, None)

def globus_transfer_client(
        client_id,
        refresh_tokens=True,
        scope=globus_sdk.scopes.TransferScopes.all,
        configname="globus-token.yml"
    ):
    """Obtain and return a Globus TransferClient configured with RefreshTokenAuthorizer.

    Args:
        client_id (str): The Globus Native App Client ID.
        refresh_tokens (bool, optional): Whether to request refresh tokens. Defaults to True.

    Returns:
        globus_sdk.TransferClient: A configured TransferClient instance.
    """
    transfer_rt = globus_transfer_rt(configname)
    if not transfer_rt:
        globus_token(client_id=client_id, scopes=scope, configname=configname)
        transfer_rt = globus_transfer_rt()
    client = globus_auth_client(client_id, refresh_tokens=refresh_tokens, scopes=scope)
    authorizer = globus_sdk.RefreshTokenAuthorizer(transfer_rt, client)
    return globus_sdk.TransferClient(authorizer=authorizer)


#######################
# File Management
#######################

def list_files(tc, collection_id, path, max_depth=3):
    """Yields file objects from a Globus collection up to a given depth.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        collection_id (str): The collection (endpoint) ID.
        path (str): The path in the Globus collection to list files from.
        max_depth (int, optional): Maximum directory nesting depth. Defaults to 3.

    Yields:
        dict: File metadata items.
    """
    def _get_files(tc, collectionid, queue, depth_limit):
        while queue:
            abs_path, rel_path, depth = queue.pop()
            path_prefix = rel_path + "/" if rel_path else ""
            res = tc.operation_ls(collectionid, path=abs_path)

            if depth < depth_limit:
                queue.extend(
                    (
                        res["path"] + item["name"],
                        path_prefix + item["name"],
                        depth + 1,
                    )
                    for item in res["DATA"]
                    if item["type"] == "dir"
                )
            for item in res["DATA"]:
                if item["type"] == 'file':
                    item["name"] = path_prefix + item["name"]
                    item["path"] = abs_path.replace('/~/', '/')
                    yield item

    queue = deque()
    queue.append((path, "", 0))
    yield from _get_files(tc, collection_id, queue, max_depth)


def data_exists(tc, collection_id, path):
    """Checks whether any file exists at the specified path in the given collection.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        collection_id (str): The collection (endpoint) ID.
        path (str): The path to check.

    Returns:
        bool: True if any file found at the specified path, otherwise False.
    """
    try:
        listing = tc.operation_ls(collection_id, path=path)
        return any(item["type"] == 'file' for item in listing["DATA"])
    except globus_sdk.TransferAPIError:
        return False


def transfer_data(tc, source_collection_id, dest_collection_id, source_path, dest_path):
    """Performs a file transfer between two Globus collections.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        source_collection_id (str): The source endpoint ID.
        dest_collection_id (str): The destination endpoint ID.
        source_path (str): The source path to transfer from.
        dest_path (str): The destination path to transfer to.
    """
    tdata = globus_sdk.TransferData(
        tc,
        source_collection_id,
        dest_collection_id,
        label="Globus Transfer",
    )
    tdata.add_item(source_path, dest_path, recursive=True)
    transfer_result = tc.submit_transfer(tdata)
    print(f"Transfer submitted. Task ID: {transfer_result['task_id']}")


if __name__ == "__main__":
    configbasepath = get_config_path()
    UUIDs = get_uuids(configbasepath)

    access_token = globus_token(client_id=UUIDs['CLIENT_ID'])
    transfer_client = globus_transfer_client(client_id=UUIDs['CLIENT_ID'])
