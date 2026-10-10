mport streamlit as st

# Page configuration
st.set_page_config(
    page_title="My First Streamlit App",
    page_icon="🚀",
    layout="wide"
)

# App title and introduction
st.title("🚀 My First Streamlit App")

st.write("Welcome! This is my first interactive Python application.")
st.write("Use the fields below to interact with the app.")

# Sidebar
st.sidebar.title("Navigation")
st.sidebar.write("Welcome to my app!")

page = st.sidebar.selectbox(
    "Choose a page:",
    ["Home", "About", "Contact"]
)

# Home page
if page == "Home":

    st.header("Home Page")

    st.write("This is the home page of my application.")

    # User input
    st.subheader("Enter Your Information")

    name = st.text_input("What is your name?")

    age = st.slider(
        "Select your age:",
        min_value=1,
        max_value=100,
        value=25
    )

    favorite_color = st.selectbox(
        "Choose your favorite color:",
        ["Red", "Blue", "Green", "Yellow", "Purple"]
    )

    # Display results
    if name:
        st.success(f"Welcome, {name}!")

        st.write("Your age is:", age)

        st.write(
            "Your favorite color is:",
            favorite_color
        )

    # Button
    if st.button("Click Me"):
        st.balloons()
        st.write("Congratulations! Your button works!")

    # Checkbox
    if st.checkbox("Show additional information"):
        st.info("You are using a Streamlit application.")

# About page
elif page == "About":

    st.header("About This App")

    st.write(
        "This application was created using Python and Streamlit."
    )

    st.write(
        "Streamlit makes it easy to build interactive web applications."
    )

# Contact page
elif page == "Contact":

    st.header("Contact Page")

    st.write("Enter your information below.")

    email = st.text_input("Your email address")

    message = st.text_area("Your message")

    if st.button("Submit Message"):

        if email and message:
            st.success("Your message has been submitted!")
        else:
            st.warning(
                "Please enter your email and message."
            )

# Footer
st.divider()

st.caption("My First Streamlit App | Powered by Python")
