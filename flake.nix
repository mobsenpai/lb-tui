{
  description = "ListenBrainz CLI/TUI music player";

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
      python = pkgs.python3;

      pythonEnv = python.withPackages (ps:
        with ps; [
          requests
          yt-dlp
          prompt-toolkit
          troi
        ]);

      lb-cli = python.pkgs.buildPythonPackage {
        pname = "lb-cli";
        version = "0.1.0";
        src = ./.;
        propagatedBuildInputs = with python.pkgs; [
          requests
          yt-dlp
          prompt-toolkit
        ];
        meta = {
          description = "ListenBrainz CLI/TUI music player";
          license = pkgs.lib.licenses.mit;
          mainProgram = "lb";
        };
      };
    in {
      packages.default = lb-cli;

      devShells.default = pkgs.mkShell {
        buildInputs = [
          pythonEnv
          pkgs.mpv
          pkgs.yt-dlp
        ];

        shellHook = ''
          # Load environment variables from .env if it exists
          if [ -f .env ]; then
            export $(grep -v '^#' .env | xargs)
            echo "✅ Loaded credentials from .env"
          else
            echo "⚠️  .env file not found. Create one from .env.template"
          fi

          # Add the current directory to PYTHONPATH so Python can find lb_cli
          export PYTHONPATH="$PWD:$PYTHONPATH"

          # Create convenient aliases
          alias lb='python -m lb_cli'
          alias lb-tui='python -m lb_cli.tui'

          echo "🎵 ListenBrainz CLI Music Environment"
          echo ""
          echo "✅ Ready! Available commands:"
          echo "  lb play \"Artist Title\""
          echo "  lb liked"
          echo "  lb weekly"
          echo "  lb-tui liked"
          echo "  lb-tui weekly"
          echo "  lb-tui playlist <mbid>"
          echo ""
        '';
      };
    });
}
