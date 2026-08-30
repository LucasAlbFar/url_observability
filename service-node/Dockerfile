# The tag carries no suffix on purpose: tests/test_compose_config.py
# accepts only a bare major.minor.patch, so `-alpine` and `-slim` are
# rejected for every image in this repo. The cost is image size; the
# alternative would be loosening the rule for all of them.
FROM node:24.20.0
WORKDIR /app
# The lockfile is copied before the source so a source edit does not
# reinstall, and `npm ci` rather than `npm install` because it installs
# exactly the lockfile and fails when the two have drifted apart. That
# failure is what makes the pin worth anything — it is this service's
# equivalent of go.sum.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY main.js ./
CMD ["node", "main.js"]
