import logging
import tempfile
import time

from googleapiclient import discovery
from googleapiclient import http

from oauth2client.client import GoogleCredentials

# Some of this is copied from:
# https://github.com/GoogleCloudPlatform/python-docs-samples/blob/master/storage/api/crud_object.py
# and:
# https://github.com/GoogleCloudPlatform/python-docs-samples/blob/master/storage/api/list_objects.py

RETRIES_BEFORE_FAILURE = 12
FIRST_RETRY_SLEEP = 2.0
_SERVICE = None


def get_service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = create_service()
    return _SERVICE


def create_service():
    # Get the application default credentials. When running locally, these are
    # available after running `gcloud init`. When running on compute
    # engine, these are available from the environment.
    credentials = GoogleCredentials.get_application_default()

    # Construct the service object for interacting with the Cloud Storage API -
    # the 'storage' service, at version 'v1'.
    # You can browse other available api services and versions here:
    #     http://g.co/dev/api-client-library/python/apis/
    return discovery.build('storage', 'v1', credentials=credentials)


def robustify(function):
    def robust_function(*args, **kwargs):
        error_num = 0
        while True:
            try:
                return function(*args, **kwargs)
            except Exception as e:
                error_num += 1
                logging.warning(
                    "Exception calling %s: '%s'. "
                    "This call has failed %d times. Will retry up to "
                    "%d times." % (
                        str(function),
                        str(e),
                        error_num,
                        RETRIES_BEFORE_FAILURE))

                if error_num > RETRIES_BEFORE_FAILURE:
                    raise

                sleep_time = FIRST_RETRY_SLEEP**error_num
                logging.warn("Sleeping for %0.2f seconds." % sleep_time)
                time.sleep(sleep_time)
    return robust_function


def split_bucket_and_name(url):
    if not url.startswith("gs://"):
        raise ValueError("Not a gs:// url: %s" % url)
    return url[len("gs://"):].split("/", 1)


@robustify
def list_contents(prefix):
    splitted = split_bucket_and_name(prefix)
    if len(splitted) == 1:
        (bucket_name, file_name_prefix) = (splitted[0], "")
    else:
        (bucket_name, file_name_prefix) = splitted

    # Create a request to objects.list to retrieve a list of objects.
    fields_to_return = \
        'nextPageToken,items(name)'
    req = get_service().objects().list(
        bucket=bucket_name,
        prefix=file_name_prefix,
        maxResults=100000,
        fields=fields_to_return)

    all_objects = []
    # If you have too many items to list in one request, list_next() will
    # automatically handle paging with the pageToken.
    while req:
        resp = req.execute()
        all_objects.extend(resp.get('items', []))
        req = get_service().objects().list_next(req, resp)
    return [item['name'] for item in all_objects]


@robustify
def move(source, dest):
    # From https://cloud.google.com/storage/docs/json_api/v1/objects/rewrite
    (bucket_name, source_object) = split_bucket_and_name(source)
    (bucket_name2, dest_object) = split_bucket_and_name(dest)
    service = get_service()

    request = service.objects().rewrite(
        sourceBucket=bucket_name,
        sourceObject=source_object,
        destinationBucket=bucket_name,
        destinationObject=dest_object,
        body={})
    request.execute()

    # Delete source.
    request = service.objects().delete(
        bucket=bucket_name,
        object=source_object)
    request.execute()


@robustify
def put(
        name,
        input_handle,
        readers=[],
        owners=[],
        mime_type='application/octet-stream'):
    input_handle.seek(0)
    (bucket_name, file_name) = split_bucket_and_name(name)

    # This is the request body as specified:
    # http://g.co/cloud/storage/docs/json_api/v1/objects/insert#request
    body = {
        'name': file_name,
    }

    # If specified, create the access control objects and add them to the
    # request body
    if readers or owners:
        body['acl'] = []

    for r in readers:
        body['acl'].append({
            'entity': 'user-%s' % r,
            'role': 'READER',
            'email': r
        })
    for o in owners:
        body['acl'].append({
            'entity': 'user-%s' % o,
            'role': 'OWNER',
            'email': o
        })

    # Now insert them into the specified bucket as a media insertion.
    req = get_service().objects().insert(
        bucket=bucket_name,
        body=body,
        # You can also just set media_body=filename, but # for the sake of
        # demonstration, pass in the more generic file handle, which could
        # very well be a StringIO or similar.
        media_body=http.MediaIoBaseUpload(input_handle, mime_type))
    resp = req.execute()

    return resp


@robustify
def get(name, output_handle=None):
    (bucket_name, file_name) = split_bucket_and_name(name)

    if output_handle is None:
        output_handle = tempfile.TemporaryFile(
            prefix="kubeface-bucket-storage-",
            suffix=".data")

    # Use get_media instead of get to get the actual contents of the object
    req = get_service().objects().get_media(
        bucket=bucket_name,
        object=file_name)
    downloader = http.MediaIoBaseDownload(output_handle, req)

    done = False
    while done is False:
        (status, done) = downloader.next_chunk()
        logging.debug("Download {}%.".format(int(status.progress() * 100)))
    output_handle.seek(0)
    return output_handle


@robustify
def delete(name):
    (bucket_name, file_name) = split_bucket_and_name(name)
    req = get_service().objects().delete(bucket=bucket_name, object=file_name)
    return req.execute()


def access_info(name):
    (bucket_name, file_name) = split_bucket_and_name(name)
    return (
        "https://storage.cloud.google.com/"
        "{bucket_name}/{file_name}\t[ {name} ]".format(
            bucket_name=bucket_name,
            file_name=file_name,
            name=name))
