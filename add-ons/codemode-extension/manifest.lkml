project_name: "lkr-codemode-extension"

application: lkr-codemode {
  label: "Looker Code Mode"
  url: "https://cdn.lkr.dev/cli/codemode/latest/codemode_extension.js"
  # url: "https://localhost:8080/codemode_extension.js"
  mount_points: {
    standalone: yes
  }
  entitlements: {
    raw_api_request: yes
    use_iframes: yes
    use_form_submit: yes
  }
}
