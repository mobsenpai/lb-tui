{
  description = "ListenBrainz CLI music player (Python script environment)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};

      # Python environment with all required packages
      pythonEnv = pkgs.python3.withPackages (ps:
        with ps; [
          requests
          yt-dlp
          troi
          prompt-toolkit
          python-mpv-jsonipc
        ]);
    in {
      devShells.default = pkgs.mkShell {
        buildInputs = [
          pythonEnv
          pkgs.mpv # for audio playback
          pkgs.yt-dlp # CLI tool (may be needed by mpv's ytdl hook)
          pkgs.jq # optional, for JSON processing
          pkgs.curl # optional, for manual API tests
        ];

        shellHook = ''
          echo "🎵 ListenBrainz Python CLI Environment"
          echo "Your script is ready to run:"
          echo "  python lb.py play \"Artist Title\""
          echo "  python lb.py weekly <username>"
          echo ""
          # Optional: set token as env var if you want to override the hardcoded one
          # export LISTENBRAINZ_TOKEN="your-token-here"
        '';
      };
    });
}
