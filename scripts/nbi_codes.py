"""
nbi_codes.py  —  Official FHWA National Bridge Inventory (NBI) code lookups.

The raw NBI (from your Excel files OR from the Hermai API) stores CODES, not names.
This module turns those codes into human-readable labels using the federal codebook,
so the "Agency responsible" value is 100% derived from the data and reproduces
identically on every rebuild.

Source of the code definitions:
  FHWA, "Recording and Coding Guide for the Structure Inventory and Appraisal of the
  Nation's Bridges" (Report FHWA-PD-96-001) and the NBI data dictionary.
  Owner = NBI Item 22 (column OWNER_022); State = Item 1 (STATE_CODE_001, FIPS);
  County = Item 3 (COUNTY_CODE_003, state county code).

Nothing here is bridge-specific or hand-entered per row — these are constant tables.
"""

# --- NBI Item 22 (Owner) : official code -> federal label -----------------------
OWNER_ITEM22 = {
    1:  "State Highway Agency",
    2:  "County Highway Agency",
    3:  "Town or Township Highway Agency",
    4:  "City or Municipal Highway Agency",
    11: "State Park, Forest or Reservation Agency",
    12: "Local Park, Forest or Reservation Agency",
    21: "Other State Agencies",
    25: "Other Local Agencies",
    26: "Private (other than railroad)",
    27: "Railroad",
    31: "State Toll Authority",
    32: "Local Toll Authority",
    60: "Other Federal Agencies",
    61: "Indian Tribal Government",
    62: "Bureau of Indian Affairs",
    63: "Bureau of Fish and Wildlife",
    64: "U.S. Forest Service",
    66: "National Park Service",
    68: "Bureau of Land Management",
    69: "Bureau of Reclamation",
    70: "Corps of Engineers (Civil)",
    72: "Corps of Engineers (Military)",
    73: "Air Force",
    74: "Navy/Marines",
    75: "Army",
    76: "NASA",
    80: "Unknown",
}

# --- State FIPS (Item 1) -> common name of that state's DOT ----------------------
# The "state highway agency" (owner code 1) for a given state is that state's DOT.
# Keyed by the FIPS state code so it is derived from STATE_CODE_001, not guessed.
STATE_DOT = {
    17: "Illinois DOT", 19: "Iowa DOT", 27: "Minnesota DOT", 29: "Missouri DOT",
    31: "Nebraska DOR", 46: "South Dakota DOT", 55: "Wisconsin DOT",
}
STATE_NAME = {17: "Illinois", 19: "Iowa", 27: "Minnesota", 29: "Missouri",
              31: "Nebraska", 46: "South Dakota", 55: "Wisconsin"}

# --- Iowa county codes (Item 3) -> county name ----------------------------------
IOWA_COUNTY = {1:'Adair',3:'Adams',5:'Allamakee',7:'Appanoose',9:'Audubon',11:'Benton',13:'Black Hawk',15:'Boone',17:'Bremer',19:'Buchanan',21:'Buena Vista',23:'Butler',25:'Calhoun',27:'Carroll',29:'Cass',31:'Cedar',33:'Cerro Gordo',35:'Cherokee',37:'Chickasaw',39:'Clarke',41:'Clay',43:'Clayton',45:'Clinton',47:'Crawford',49:'Dallas',51:'Davis',53:'Decatur',55:'Delaware',57:'Des Moines',59:'Dickinson',61:'Dubuque',63:'Emmet',65:'Fayette',67:'Floyd',69:'Franklin',71:'Fremont',73:'Greene',75:'Grundy',77:'Guthrie',79:'Hamilton',81:'Hancock',83:'Hardin',85:'Harrison',87:'Henry',89:'Howard',91:'Humboldt',93:'Ida',95:'Iowa',97:'Jackson',99:'Jasper',101:'Jefferson',103:'Johnson',105:'Jones',107:'Keokuk',109:'Kossuth',111:'Lee',113:'Linn',115:'Louisa',117:'Lucas',119:'Lyon',121:'Madison',123:'Mahaska',125:'Marion',127:'Marshall',129:'Mills',131:'Mitchell',133:'Monona',135:'Monroe',137:'Montgomery',139:'Muscatine',141:"O'Brien",143:'Osceola',145:'Page',147:'Palo Alto',149:'Plymouth',151:'Pocahontas',153:'Polk',155:'Pottawattamie',157:'Poweshiek',159:'Ringgold',161:'Sac',163:'Scott',165:'Shelby',167:'Sioux',169:'Story',171:'Tama',173:'Taylor',175:'Union',177:'Van Buren',179:'Wapello',181:'Warren',183:'Washington',185:'Wayne',187:'Webster',189:'Winnebago',191:'Winneshiek',193:'Woodbury',195:'Worth',197:'Wright'}


def _int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def agency(owner_code, state_code=19, county_code=None):
    """Return the responsible agency, derived only from NBI codes.

    owner_code  = NBI Item 22 (OWNER_022)
    state_code  = NBI Item 1  (STATE_CODE_001, FIPS)  [default 19 = Iowa]
    county_code = NBI Item 3  (COUNTY_CODE_003)
    """
    o = _int(owner_code); s = _int(state_code); c = _int(county_code)
    state = STATE_NAME.get(s, f"State {s}")
    county = IOWA_COUNTY.get(c) if s == 19 else None

    if o == 1:                                   # State Highway Agency -> that state's DOT
        return STATE_DOT.get(s, f"{state} State Highway Agency")
    if o == 2:                                   # County Highway Agency
        return f"{county} County" if county else "County Highway Agency"
    if o == 3:
        return f"{county} County (town/township)" if county else "Town/Township"
    if o == 4:
        return "City / Municipal"
    if o == 21:
        return f"Other {state} state agency"
    if o == 31:
        return f"{state} Toll Authority"
    if o == 32:
        return "Local Toll Authority"
    if o in OWNER_ITEM22:
        return OWNER_ITEM22[o]
    return f"NBI owner code {o}"


def owner_category(owner_code):
    """Short badge label, also derived straight from Item 22."""
    o = _int(owner_code)
    return {1: "State DOT", 2: "County", 3: "Township", 4: "City"}.get(o, "Other")


if __name__ == "__main__":
    # quick self-test against known bridges
    print("US 67 (owner 1, state 19):      ", agency(1, 19, 163))   # -> Iowa DOT
    print("Burlington St (owner 4, Johnson):", agency(4, 19, 103))  # -> City / Municipal
    print("A county bridge (owner 2, 103):  ", agency(2, 19, 103))  # -> Johnson County
