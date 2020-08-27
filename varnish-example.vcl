vcl 4.0;

backend default {
  .host = "127.0.0.1";
  .port = "8000";
}

sub vcl_deliver {
    if (resp.status == 307) {
        set req.url = resp.http.Location;
        return(restart);
    }
}
