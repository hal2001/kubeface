import time
from six import BytesIO
from numpy import testing

from kubeface import bucket_storage, storage

from .util import with_local_and_bucket_storage


def test_url_parse():
    testing.assert_equal(
        bucket_storage.split_bucket_and_name("gs://foo/bar"),
        ("foo", "bar"))

    testing.assert_equal(
        bucket_storage.split_bucket_and_name("gs://foo/bar/baz.txt"),
        ("foo", "bar/baz.txt"))


@with_local_and_bucket_storage
def test_put_and_get_to_bucket(bucket):
    data = "ABCDe" * 1000
    data_handle = BytesIO(data.encode("UTF-8"))
    file_name = "kubeface-test-%s.txt" % (
        str(time.time()).replace(".", ""))
    name = "%s/%s" % (bucket, file_name)
    storage.put(name, data_handle)
    testing.assert_equal(storage.list_contents(name), [file_name])
    testing.assert_(
        file_name in storage.list_contents("%s/kubeface-test-" % bucket))

    result_handle = storage.get(name)
    testing.assert_equal(result_handle.read().decode("UTF-8"), data)
    storage.delete(name)
    testing.assert_(
        file_name not in storage.list_contents("%s/" % bucket))


@with_local_and_bucket_storage
def test_move(bucket):
    data = "ABCDe" * 1000
    data_handle = BytesIO(data.encode("UTF-8"))
    file_name = "kubeface-test-%s.txt" % (
        str(time.time()).replace(".", ""))
    name = "%s/%s" % (bucket, file_name)
    name2 = "%s/moved-%s" % (bucket, file_name)
    storage.put(name, data_handle)
    testing.assert_equal(storage.list_contents(name), [file_name])
    storage.move(name, name2)
    testing.assert_equal(storage.list_contents(name), [])
    testing.assert_equal(
        storage.list_contents(name2),
        ["moved-%s" % file_name])
    result_handle = storage.get(name2)
    testing.assert_equal(result_handle.read().decode("UTF-8"), data)
    storage.delete(name2)
    testing.assert_(
        ("moved-%s" % file_name) not in storage.list_contents("%s/" % bucket))
