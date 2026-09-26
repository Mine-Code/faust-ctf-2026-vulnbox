CREATE TABLE users (
	id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
	name VARCHAR(128) UNIQUE,
	password VARCHAR(128) NOT NULL,
	created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tokens (
	token UUID DEFAULT gen_random_uuid() PRIMARY KEY,
	"user" UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE invalid_tokens (
	token UUID NOT NULL REFERENCES tokens(token) ON DELETE CASCADE
);

CREATE VIEW valid_tokens AS
SELECT * FROM tokens WHERE token NOT IN (SELECT token FROM invalid_tokens);

CREATE TABLE rents (
	id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
	"user" UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	pilotfirstname VARCHAR(128) NOT NULL,
	pilotlastname VARCHAR(128) NOT NULL,
	startdate TIMESTAMP NOT NULL,
	enddate TIMESTAMP NOT NULL,
	vehicle VARCHAR(128) NOT NULL,
	receiptcode VARCHAR(5000) NOT NULL,
	created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE FUNCTION delete_old_users() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  DELETE FROM users WHERE created < CURRENT_TIMESTAMP - INTERVAL '25 minutes';
  RETURN NULL;
END;
$$;

CREATE TRIGGER trigger_delete_old_users
    AFTER INSERT ON users
    EXECUTE PROCEDURE delete_old_users();