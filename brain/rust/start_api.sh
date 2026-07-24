#!/bin/bash
# Wrapper so launchd spawns an Apple-signed shell rather than the ad-hoc binary directly.
# All env vars are set in com.brain.api.plist and inherited here.
exec "/Users/abundancia888/Documents/AI/brain/rust/target/release/brain_api"
