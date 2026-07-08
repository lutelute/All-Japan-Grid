function solve_pf(island, mode)
%SOLVE_PF  All-Japan-Grid の MATPOWER 配布ケースで潮流計算 (MATLAB / MATPOWER 版).
%
%   配布物 dist/matpower_national/<island>.mat を読み、MATPOWER の runpf で
%   AC 潮流を解きます。収束しない場合は rundcpf (DC) に自動フォールバック。
%
%   対象は非同期 4 島 (北海道 50Hz / 東日本 50Hz / 西日本 60Hz / 沖縄 60Hz)。
%   各 .mat は runpf 用 (発電コスト gencost 無し = runopf 不可・通常潮流のみ)。
%
%   使い方:
%     solve_pf                 % okinawa (最小・数秒)
%     solve_pf('hokkaido')
%     solve_pf('east', 'dc')   % DC 潮流を直接
%
%   事前準備 (MATPOWER の導入):
%     このスクリプトは MATPOWER のパスを直書きしません。実行前にご自身の
%     環境に合わせて MATPOWER を path に通してください。例:
%       addpath(genpath('/path/to/matpower8.1'));
%     MATPOWER: https://matpower.org/  (BSD-3-Clause)

    if nargin < 1 || isempty(island), island = 'okinawa'; end
    if nargin < 2, mode = 'ac'; end

    % --- MATPOWER が path 上にあるか確認 (パスは各自で addpath 済みの前提) ---
    if exist('runpf', 'file') ~= 2
        error(['MATPOWER が見つかりません。実行前に addpath で MATPOWER を' ...
               ' path に通してください。\n' ...
               '  例: addpath(genpath(''/path/to/matpower8.1''));']);
    end

    % --- 配布ケース .mat を解決 (このファイルからの相対パス) ---
    here = fileparts(mfilename('fullpath'));
    matfile = fullfile(here, '..', '..', 'dist', 'matpower_national', [island '.mat']);
    if exist(matfile, 'file') ~= 2
        error('ケースが見つかりません: %s', matfile);
    end

    fprintf('=== %s ===\n', island);
    fprintf('case: %s\n', matfile);
    mpc = loadcase(matfile);
    % 配布ケースは表示用の bus_name を同梱するが、MATPOWER の ext2int が
    % 並べ替え時に一部環境で失敗する。潮流計算には不要なので除去する
    % (バス名は dist/matpower_national/<island>_busname.csv で参照可)。
    if isfield(mpc, 'bus_name')
        mpc = rmfield(mpc, 'bus_name');
    end
    fprintf('loaded: %d bus, %d branch, %d gen\n', ...
        size(mpc.bus, 1), size(mpc.branch, 1), size(mpc.gen, 1));

    mpopt = mpoption('verbose', 0, 'out.all', 0, 'pf.nr.max_it', 100);

    ac_ok = false;
    if strcmpi(mode, 'ac')
        res = runpf(mpc, mpopt);
        ac_ok = res.success;
        if ~ac_ok
            fprintf('AC (Newton-Raphson) not converged -> DC fallback\n');
            res = rundcpf(mpc, mpopt);
        end
    else
        res = rundcpf(mpc, mpopt);
    end

    if ~res.success
        fprintf('RESULT: NOT CONVERGED\n');
        return;
    end

    % MATPOWER 列定義: bus(:,3)=PD, gen(:,2)=PG, branch(:,14)+(:,16)=損失
    total_gen  = sum(res.gen(:, 2));
    total_load = sum(res.bus(:, 3));
    if ac_ok
        loss = sum(res.branch(:, 14) + res.branch(:, 16));
        vm = res.bus(:, 8);
        fprintf('RESULT: AC CONVERGED\n');
        fprintf('  total generation: %10.0f MW\n', total_gen);
        fprintf('  total load:       %10.0f MW\n', total_load);
        fprintf('  transmission loss:%10.0f MW  (%.2f %% of load)\n', ...
            loss, loss / max(total_load, 1) * 100);
        fprintf('  voltage Vm:        %.3f - %.3f pu\n', min(vm), max(vm));
        % 健全性メモ: MATPOWER は多成分島の複数 slack も正しく扱い、各成分で需給を
        % 閉じます (実機確認: okinawa 損失 2.2% / hokkaido +3.5%)。ただし配布ケースは
        % 建造断面のスナップショットで需給が厳密調整されたものではないため、損失が
        % 負や過大な場合は内訳の不整合を疑ってください (「収束」==「正しく」ではない)。
        if loss < 0 || loss / max(total_load, 1) > 0.20
            fprintf('  [注意] 損失が負 or 過大です。需給内訳の不整合を確認してください。\n');
        end
    else
        fprintf('RESULT: DC CONVERGED\n');
        fprintf('  total generation: %10.0f MW\n', total_gen);
        fprintf('  total load:       %10.0f MW\n', total_load);
    end
end
