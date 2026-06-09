// Import Ink's index to trigger the reconciler module load
import { render, Box, Text } from 'ink';
import React, { useState, useEffect } from 'react';
import { Readable, Writable } from 'node:stream';

// Check if we can find batchedUpdates via React's internals
const ReactInternals = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
console.log('React internals keys:', Object.keys(ReactInternals));
