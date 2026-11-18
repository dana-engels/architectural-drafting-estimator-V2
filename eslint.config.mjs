export default [{
  files: ["static/**/*.js"],
  languageOptions: {
    globals: { document: "readonly" },
  },
  rules: {
    "eqeqeq": "error",
    "no-constant-condition": "error",
    "no-dupe-args": "error",
    "no-duplicate-case": "error",
    "no-empty": "error",
    "no-redeclare": "error",
    "no-undef": "error",
    "no-unreachable": "error",
    "no-unused-vars": "error",
    "no-unsafe-optional-chaining": "error",
    "no-useless-escape": "error",
    "no-var": "error",
    "prefer-const": "error",
  },
}];
