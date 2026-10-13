-- disable snippe payment provider
UPDATE payment_provider
   SET snippe_api_key = NULL,
       snippe_webhook_secret = NULL;
