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
          maintainer: 'Vitrail',
          homepage: 'https://signflow.io',
          description: 'Vitrail Digital Signage Player',
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
