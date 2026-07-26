SESSION_COOKIE_NAME = "rakit_session"
CSRF_COOKIE_NAME = "rakit_csrf"

# A separate pre-session CSRF cookie for the login POST itself. Login is
# the only unauthenticated state-changing endpoint, so it has no
# `session_id` to bind a normal CSRF token to -- this one is a pure
# double-submit value, issued when the login page is rendered.
LOGIN_CSRF_COOKIE_NAME = "rakit_login_csrf"
