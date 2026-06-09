import React, { useState, useEffect } from 'react';
import createReconciler from 'react-reconciler';

// Create a minimal reconciler instance just to access flushSync
const miniReconciler = createReconciler({
  getRootHostContext: () => ({}),
  prepareForCommit: () => null,
  resetAfterCommit: () => {},
  getChildHostContext: () => ({}),
  shouldSetTextContent: () => false,
  createInstance: (type, props) => ({ type, props, children: [] }),
  createTextInstance: (text) => ({ text }),
  appendInitialChild: (parent, child) => parent.children.push(child),
  appendChild: (parent, child) => parent.children.push(child),
  appendChildToContainer: (parent, child) => parent.children.push(child),
  insertBefore: () => {},
  insertInContainerBefore: () => {},
  removeChild: () => {},
  removeChildFromContainer: () => {},
  prepareUpdate: () => ({}),
  commitUpdate: () => {},
  commitTextUpdate: () => {},
  resetTextContent: () => {},
  clearContainer: () => false,
  getPublicInstance: i => i,
  preparePortalMount: () => {},
  finalizeInitialChildren: () => false,
  detachDeletedInstance: () => {},
  isPrimaryRenderer: false,  // NOT primary
  supportsMutation: true,
  supportsPersistence: false,
  supportsHydration: false,
  scheduleTimeout: setTimeout,
  cancelTimeout: clearTimeout,
  noTimeout: -1,
  getCurrentEventPriority: () => 0,
  beforeActiveInstanceBlur: () => {},
  afterActiveInstanceBlur: () => {},
  getInstanceFromNode: () => null,
  prepareScopeUpdate: () => {},
  getInstanceFromScope: () => null,
});

console.log('miniReconciler has flushSync:', typeof miniReconciler.flushSync);
console.log('miniReconciler has batchedUpdates:', typeof miniReconciler.batchedUpdates);
