"""Transaction Search setup is idempotent. No AWS calls."""


def test_an_already_set_destination_does_not_stop_the_deploy(monkeypatch):
    import boto3

    from deploy import enable_transaction_search

    class AlreadySet(Exception):
        pass

    class Client:
        class exceptions:
            InvalidRequestException = AlreadySet

        def update_trace_segment_destination(self, Destination):
            raise AlreadySet("The destination is already set to CloudWatchLogs")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Client())

    enable_transaction_search()
