#!/bin/sh

(while [ -p redisout.tex ]; do cat redisout.tex; done) | nc redis 6379
