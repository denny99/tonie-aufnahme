// semantic-release: jeder Push auf main mit feat:/fix:/BREAKING CHANGE erzeugt ein Release mit .deb und AppImage.
const hinweis = require('fs').readFileSync('packaging/release-notes.md', 'utf8');

module.exports = {
  branches: ['main'],
  tagFormat: 'v${version}',
  plugins: [
    ['@semantic-release/commit-analyzer', { preset: 'conventionalcommits' }],
    ['@semantic-release/release-notes-generator', { preset: 'conventionalcommits' }],
    ['@semantic-release/exec', { prepareCmd: './packaging/build-all.sh ${nextRelease.version}' }],
    ['@semantic-release/github', {
      assets: [
        { path: 'dist/*.deb', label: 'Debian/Ubuntu-Paket (.deb)' },
        { path: 'dist/*.AppImage', label: 'AppImage (jedes Linux)' },
        { path: 'dist/SHA256SUMS', label: 'Prüfsummen' },
      ],
      releaseNameTemplate: 'Tonie-Aufnahme <%= nextRelease.version %>',
      releaseBodyTemplate: hinweis + '\n\n<%= nextRelease.notes %>',
      successComment: false,
    }],
  ],
};
