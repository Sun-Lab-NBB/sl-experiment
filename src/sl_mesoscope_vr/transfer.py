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
        configname="globus-token.yml",
        force_refresh=False
    ):
    """Obtain and return a Globus TransferClient configured with RefreshTokenAuthorizer.

    Args:
        client_id (str): The Globus Native App Client ID.
        refresh_tokens (bool, optional): Whether to request refresh tokens. Defaults to True.

    Returns:
        globus_sdk.TransferClient: A configured TransferClient instance.
    """
    transfer_rt = globus_transfer_rt(configname)
    if not transfer_rt or force_refresh:
        globus_token(client_id=client_id, scopes=scope, configname=configname)
        transfer_rt = globus_transfer_rt()
    client = globus_auth_client(client_id, refresh_tokens=refresh_tokens, scopes=scope)
    authorizer = globus_sdk.RefreshTokenAuthorizer(transfer_rt, client)
    return globus_sdk.TransferClient(authorizer=authorizer)


#######################
# File Management
#######################

def list_files(tc, collection_id, path, max_depth=1):
    """Yields file objects from a Globus collection up to a given depth.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        collection_id (str): The collection (endpoint) ID.
        path (str): The path in the Globus collection to list files from.
        max_depth (int, optional): Maximum directory nesting depth. Defaults to 1.

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
    """Checks whether any file or directory exists at the specified path in the given collection.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        collection_id (str): The collection (endpoint) ID.
        path (str): The path to check.

    Returns:
        bool: True if any file found at the specified path, otherwise False.
    """
    try:
        response = tc.operation_stat(collection_id, path=path)
        return response["name"] == os.path.basename(path.rstrip("/"))
    except globus_sdk.TransferAPIError:
        return False


# deep search for mismatched files recursively in the source and destination
def deep_search_mismatched_files(tc, src_collection_id, dst_collection_id, src_path, dst_path, max_depth=3):
    """Deep search for mismatched files in the source and destination collections.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        src_collection_id (str): The source collection ID.
        dst_collection_id (str): The destination collection ID.
        src_path (str): The source path.
        dst_path (str): The destination path.

    Yields:
        tuple: A tuple of source and destination file metadata items.
    """
    src_files = list_files(tc, src_collection_id, src_path, max_depth=max_depth)
    dst_files = list_files(tc, dst_collection_id, dst_path, max_depth=max_depth)
    src_files = {f["name"]: f for f in src_files}
    dst_files = {f["name"]: f for f in dst_files}

    for src_file in src_files.values():
        dst_file = dst_files.get(src_file["name"], None)
        if dst_file is None:
            yield src_file, None
        elif src_file["size"] != dst_file["size"]:
            yield src_file, dst_file

    for dst_file in dst_files.values():
        if dst_file["name"] not in src_files:
            yield None, dst_file

    return None, None


def transfer_data(
        tc, client_id, src_collection_id, dst_collection_id, src_path, dst_path,
        dry_run=False
    ):
    """Performs a file transfer between two Globus collections.

    Args:
        tc (globus_sdk.TransferClient): A TransferClient instance.
        src_collection_id (str): The source endpoint ID.
        dst_collection_id (str): The destination endpoint ID.
        src_path (str): The source path to transfer from.
        dst_path (str): The destination path to transfer to.
    """
    src_name = tc.get_endpoint(src_collection_id)["display_name"]
    dst_name = tc.get_endpoint(dst_collection_id)["display_name"]
    label = f'{os.path.basename(src_path)} from ' + \
        f'{src_name} to {dst_name}'  # noqa: ISC003

    # Autoactivate the endpoints
    tc.endpoint_autoactivate(src_collection_id)
    tc.endpoint_autoactivate(dst_collection_id)
    tdata = globus_sdk.TransferData(
        tc,
        src_collection_id,
        dst_collection_id,
        label=label[0: min(len(label), 128)].strip(),
    )
    tdata.add_item(src_path, dst_path, recursive=True)

    response = None
    if dry_run:
        return response

    try:
        # Submit transfer
        response = tc.submit_transfer(tdata)
    except globus_sdk.TransferAPIError as err:
        # Handle ConsentRequired error and re-login if necessary
        if not err.info.consent_required:
            raise
        print(
            "Encountered a ConsentRequired error.\n"
            "You must login a second time to grant consents.\n\n"
        )
        print(err.info.consent_required.required_scopes)
        tc = globus_transfer_client(client_id=client_id, scope=err.info.consent_required.required_scopes, force_refresh=True)

    if response is None:
        return response

    task_id = response.get('task_id', None)
    message = response.get('message', None)
    print(f"Transfer submitted. Task ID: {task_id} - {message}")

    return task_id


def transfer_data_with_retries(
        tc, client_id, src_collection_id, dst_collection_ids, src_path, dst_path
    ):
    dst_collection_id = next(dst_collection_ids)
    response = None
    transfer_abort = False
    while (
            not transfer_abort
            or (
                response is not None
                and tc.get_task(response["task_id"])["status"] in ("SUCCEEDED", "FAILED")
            )
        ):
        try:
            response = transfer_data(tc, client_id, src_collection_id, dst_collection_id, src_path, dst_path)
        except globus_sdk.TransferAPIError as e:
            print(e)
            try:
                dst_collection_id = next(dst_collection_ids)
            except StopIteration:
                transfer_abort = True

    return response


if __name__ == "__main__":
    configbasepath = get_config_path()
    UUIDs = get_uuids(configbasepath)

    transfer_client = globus_transfer_client(client_id=UUIDs['CLIENT_ID'])

    mismatched_files = deep_search_mismatched_files(transfer_client, UUIDs['LOCAL_COLLECTION_ID'], UUIDs['SERVER_COLLECTION_ID'][1], '/~/abc/', '/home/kg574/')
    for mismatch in mismatched_files:
        print(mismatch)
