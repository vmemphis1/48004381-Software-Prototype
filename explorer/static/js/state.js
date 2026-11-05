export const state = {
  questions: [],
  activeQuestionId: null,
  builder: null,
  builderMode: 'guided',
  builderSparql: null,
};

/** Merge a patch into shared application state. */
export function setState(patch) {
  Object.assign(state, patch);
}
