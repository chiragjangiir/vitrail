module.exports = {
  packagerConfig: {
    asar: true,
    executableName: 'signflow-player',
  },
  makers: [
    {
      name: '@electron-forge/maker-deb',
      config: {
        options: {
          maintainer: 'SignFlow',
          homepage: 'https://signflow.io',
          description: 'SignFlow Digital Signage Player',
          categories: ['Utility'],
        },
      },
    },
    {
      name: '@electron-forge/maker-zip',
      platforms: ['linux'],
    },
  ],
};
