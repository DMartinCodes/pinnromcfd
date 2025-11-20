#!/usr/bin/env python3
import argparse
from pathlib import Path
import re
import logging


DEFAULT_FIELDS = ["U", "k", "nut", "omega", "p", "phi"]



def setup_logging(log_path: Path):
    """
    Configure logging so output goes both to terminal and to log_path.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove any existing handlers
    for h in logger.handlers[:]:
        logger.removeHandler(h)

    # File handler
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    fh_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)




def is_time_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    name = p.name
    if name in ("system", "constant", "0.orig"):
        return False
    try:
        float(name)
        return True
    except ValueError:
        return False


def parse_internal_field_lines(lines):
    """
    Return (data_lines, is_uniform).

    For uniform fields, data_lines[0] is a single string (scalar or vector).
    For nonuniform fields, data_lines is the list of value lines between '(' and ')'.
    """
    idx = None
    for i, line in enumerate(lines):
        if "internalField" in line:
            idx = i
            break
    if idx is None:
        raise ValueError("No internalField found in file")

    line = lines[idx]

    # Uniform: must contain 'uniform' but NOT 'nonuniform'
    if "uniform" in line and "nonuniform" not in line:
        after = line.split("uniform", 1)[1]
        after = after.replace(";", " ").strip()
        return [after], True

    # Nonuniform: internalField nonuniform List<...>
    n_idx = None
    for i in range(idx, len(lines)):
        if re.match(r"^\s*\d+\s*$", lines[i]):
            n_idx = i
            break
    if n_idx is None:
        raise ValueError("Could not find number of entries for nonuniform internalField")

    start_idx = None
    for i in range(n_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "(":
            start_idx = i + 1
            break
    if start_idx is None:
        raise ValueError("Could not find opening '(' for value list")

    data_lines = []
    for i in range(start_idx, len(lines)):
        stripped = lines[i].strip()
        if stripped in (")", ");"):
            break
        if not stripped or stripped.startswith("//"):
            continue
        data_lines.append(stripped)

    return data_lines, False


def parse_scalar_field(path: Path):
    with path.open("r") as f:
        lines = f.readlines()

    data_lines, is_uniform = parse_internal_field_lines(lines)

    if is_uniform:
        vstr = data_lines[0].strip()
        vstr = vstr.strip("()")
        first = vstr.split()[0]
        value = float(first)
        return [value]

    values = []
    for ln in data_lines:
        ln = ln.replace(";", " ").strip()
        if not ln:
            continue
        values.append(float(ln))
    return values


def parse_vector_field(path: Path):
    with path.open("r") as f:
        lines = f.readlines()

    data_lines, is_uniform = parse_internal_field_lines(lines)

    if is_uniform:
        vstr = data_lines[0].strip()
        vstr = vstr.strip("()")
        parts = vstr.split()
        if len(parts) != 3:
            raise ValueError(f"Expected 3 components in uniform vector, got: {vstr}")
        ux, uy, uz = map(float, parts)
        return [(ux, uy, uz)]

    vectors = []
    for ln in data_lines:
        ln = ln.strip().rstrip(";")
        if ln.startswith("(") and ln.endswith(")"):
            ln = ln[1:-1]
        parts = ln.split()
        if len(parts) != 3:
            raise ValueError(f"Expected 3 components in vector, got: {ln}")
        ux, uy, uz = map(float, parts)
        vectors.append((ux, uy, uz))
    return vectors


def write_scalar_csv(values, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        f.write("cellId,value\n")
        for i, v in enumerate(values):
            f.write(f"{i},{v}\n")


def write_vector_csv(vectors, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        f.write("cellId,ux,uy,uz\n")
        for i, (ux, uy, uz) in enumerate(vectors):
            f.write(f"{i},{ux},{uy},{uz}\n")


def process_case(case_dir: Path, fields):
    # where to put CSVs: sibling folder "<case_name>_csv"
    out_root = case_dir.with_name(case_dir.name + "_csv")
    out_root.mkdir(parents=True, exist_ok=True)

    log_path = out_root / "log.txt"
    setup_logging(log_path)

    logging.info(f"Starting CSV export for case: {case_dir}")
    logging.info(f"Output folder: {out_root}")


    time_dirs = sorted([d for d in case_dir.iterdir() if is_time_dir(d)],
                       key=lambda p: float(p.name))

    logging.info(f"Found {len(time_dirs)} time directories in {case_dir}")
    logging.info(f"Writing CSV output under {out_root}")

    for tdir in time_dirs:
        logging.info(f"\n=== Time {tdir.name} ===")
        out_time_dir = out_root / tdir.name

        for field in fields:
            field_path = tdir / field
            if not field_path.exists():
                logging.info(f"  [skip] {field} not found in {tdir}")
                continue

            out_path = out_time_dir / f"{field}.csv"
            try:
                if field == "U":
                    logging.info(f"  [vector] Converting {field_path} -> {out_path}")
                    vectors = parse_vector_field(field_path)
                    write_vector_csv(vectors, out_path)
                else:
                    logging.info(f"  [scalar] Converting {field_path} -> {out_path}")
                    values = parse_scalar_field(field_path)
                    write_scalar_csv(values, out_path)
            except Exception as e:
                logging.info(f"  [error] Failed to convert {field_path}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenFOAM field files (U, k, nut, omega, p, phi) to CSV per time directory."
    )
    parser.add_argument("case_dir", type=str,
                        help="Path to the OpenFOAM case directory (containing time folders, system, constant)")
    parser.add_argument("--fields", nargs="+", default=DEFAULT_FIELDS,
                        help=f"Fields to export (default: {' '.join(DEFAULT_FIELDS)})")

    args = parser.parse_args()
    case_dir = Path(args.case_dir).resolve()

    if not case_dir.exists():
        raise SystemExit(f"Case directory does not exist: {case_dir}")

    process_case(case_dir, args.fields)


if __name__ == "__main__":
    main()
